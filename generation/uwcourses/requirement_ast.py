import re
from typing import Union

from uwcourses.json_serializable import JsonSerializable

token_specs = [
    (r"\(", "LPAREN"),
    (r"\)", "RPAREN"),
    (r"\bAND\b", "AND"),
    (r"\bOR\b|;", "OR"),
    (r"\,", "COMMA"),
]

leaf_like = {"TEXT", "COURSE"}

tokenizer_regex = "|".join(f"(?P<{name}>{pattern})" for pattern, name in token_specs)
tokenizer_re = re.compile(tokenizer_regex, re.IGNORECASE)

exclusion_regex = r"\bnot\b"
exclusion_re = re.compile(exclusion_regex, re.IGNORECASE)


def wrap_sentences(linked_requisite_text):
    output = []
    need_open_paren = True

    for token in linked_requisite_text:
        if isinstance(token, str):
            parts = re.split(r"([.!?])", token)
            for i, part in enumerate(parts):
                if not part:
                    continue

                if i % 2 == 0:
                    text = part
                    if need_open_paren:
                        stripped = text.lstrip()
                        if not stripped:
                            continue
                        text = "(" + stripped
                        need_open_paren = False
                    output.append(text)

                else:
                    if output and isinstance(output[-1], str):
                        output[-1] += part + ")"
                    else:
                        if need_open_paren:
                            output.append("(" + part + ")")
                        else:
                            output.append(part + ")")
                    need_open_paren = True

        else:
            if need_open_paren:
                output.append("(")
                need_open_paren = False
            output.append(token)

    if not need_open_paren:
        if output and isinstance(output[-1], str):
            output[-1] += ")"
        else:
            output.append(")")

    return output


def infer_commas(tokens):
    """
    Infers the commas in the tokenized list of requisites.
    For example, if the tokens are:
    [('COURSE', 'CS101'), ('COMMA', ','), ('COURSE', 'CS102'), ('AND', 'AND'), ('COURSE', 'CS103')],
    it will infer that the comma is an AND operator.
    The output will be:
    [('COURSE', 'CS101'), ('AND', ','), ('COURSE', 'CS102'), ('AND', 'AND'), ('COURSE', 'CS103')].
    """
    inferred_tokens = []

    for i, (kind, value) in enumerate(tokens):
        if kind != "COMMA":
            inferred_tokens.append((kind, value))
            continue

        depth = 0
        assumed_operator = "AND"
        for next_kind, next_value in tokens[i + 1 :]:
            if next_kind == "LPAREN":
                depth += 1
            elif next_kind == "RPAREN":
                depth -= 1

            if next_kind in ("AND", "OR") and depth == 0:
                assumed_operator = next_kind
                break

        inferred_tokens.append((assumed_operator, value))

    return inferred_tokens


def collapse_operators(tokens):
    """
    Processes a list of tokens, collapsing consecutive identical logical operators
    ('AND', 'OR') into a single occurrence while retaining their order.

    The function iterates through the input tokens and ensures that consecutive
    logical operators of the same type do not appear more than once in the sequence.
    Other tokens are added to the output verbatim.

    Args:
        tokens (list[tuple[str, str]]): List of tokens where each token is a tuple
            containing the type of the token (e.g., 'AND', 'OR', or others) and its
            associated value.

    Returns:
        list[tuple[str, str]]: A new list of tokens with consecutive occurrences of
        the same logical operator collapsed.
    """
    out = []
    last_operator = None

    for kind, value in tokens:
        if kind in ("AND", "OR"):
            if last_operator != kind:
                out.append((kind, value))
                last_operator = kind
        else:
            out.append((kind, value))
            last_operator = None

    return out


def hoist_group_operators(tokens: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    Transforms a list of tokens by hoisting group operators (`AND`, `OR`) when applicable.

    In the case where a group operator is followed by a token of type `LPAREN`, we need to hoist the group operator
    before the `LPAREN` token, as the AST parser expects leaf-like tokens to precede the parentheses.

    Args:
        tokens (list[tuple[str, str]]): A list of tokens, where each token is a tuple
            containing a string type (e.g., 'LPAREN', 'AND', 'OR') and its corresponding
            value.

    Returns:
        list[tuple[str, str]]: A list of tokens transformed according to the logic
            specified, with group operators correctly hoisted for further processing.
    """
    out = []
    i = 0
    while i < len(tokens):
        kind, val = tokens[i]
        if (
            kind == "LPAREN"
            and i + 1 < len(tokens)
            and tokens[i + 1][0] in ("AND", "OR")
        ):
            op_kind, op_val = tokens[i + 1]
            if out and out[-1][0] not in ("LPAREN", "AND", "OR"):
                out.append((op_kind, op_val))
            out.append((kind, val))
            i += 2
        else:
            out.append((kind, val))
            i += 1
    return out


def filter_tokens(tokens):
    res, i = [], 0
    while i < len(tokens):
        typ, lit = tokens[i]

        if typ == "LPAREN":
            # explicitly initialize j so it's always in scope
            j = i + 1
            depth = 1
            # walk forward until we close this group
            while j < len(tokens) and depth:
                if tokens[j][0] == "LPAREN":
                    depth += 1
                elif tokens[j][0] == "RPAREN":
                    depth -= 1
                j += 1
            # now tokens[i] is 'LPAREN' and tokens[j-1] is its matching 'RPAREN'
            inner = tokens[i + 1 : j - 1]
            # only consider TEXT tokens for "not"
            has_not = any(exclusion_re.search(text) for t, text in inner if t == "TEXT")
            if not has_not:
                res.append(tokens[i])  # keep LPAREN
                res += filter_tokens(inner)  # recurse inside
                res.append(tokens[j - 1])  # keep RPAREN
            i = j  # jump past this group

        else:
            # plain run up to next LPAREN
            j = i
            while j < len(tokens) and tokens[j][0] != "LPAREN":
                j += 1
            run = tokens[i:j]
            has_not = any(exclusion_re.search(text) for t, text in run if t == "TEXT")
            if not has_not:
                res.extend(run)
            i = j

    return res


def tokenize_requisites(linked_requisite_text):
    from uwcourses.course import Course

    linked_requisite_text = wrap_sentences(linked_requisite_text)
    tokens = []

    for piece in linked_requisite_text:
        if isinstance(piece, Course.Reference):
            tokens.append(("COURSE", piece))
            continue

        position = 0
        for match in tokenizer_re.finditer(piece):
            if position < match.start() and piece[position : match.start()].strip():
                tokens.append(("TEXT", piece[position : match.start()].strip()))

            token_type = match.lastgroup
            token_value = match.group(token_type)

            tokens.append((token_type, token_value))
            position = match.end()

        if position < len(piece) and piece[position:].strip():
            tokens.append(("TEXT", piece[position:].strip()))

    tokens = infer_commas(tokens)
    tokens = hoist_group_operators(tokens)
    tokens = collapse_operators(tokens)
    tokens = filter_tokens(tokens)
    return tokens


class Leaf(JsonSerializable):
    def __init__(self, payload: JsonSerializable | str):
        self.payload = payload

    @classmethod
    def from_json(cls, json_data) -> "Leaf":
        from uwcourses.course import Course

        if isinstance(json_data, str):
            return cls(json_data)
        elif isinstance(json_data, dict):
            return cls(Course.Reference.from_json(json_data))
        else:
            raise ValueError("Invalid JSON data for Leaf")

    def to_dict(self):
        if isinstance(self.payload, JsonSerializable):
            return self.payload.to_dict()
        return str(self.payload)


class Node(JsonSerializable):
    def __init__(self, operator: str, children: list[Union["Node", Leaf]]):
        self.operator = operator
        self.children = children

    @classmethod
    def from_json(cls, json_data) -> "Union[Node, Leaf]":
        if isinstance(json_data, dict):
            operator = json_data.get("operator")
            if operator is None:
                return Leaf.from_json(json_data)
            children = [cls.from_json(child) for child in json_data.get("children", [])]
            return cls(operator, children)
        elif isinstance(json_data, str):
            return Leaf.from_json(json_data)
        else:
            raise ValueError("Invalid JSON data for Node")

    def to_dict(self):
        return {
            "operator": self.operator,
            "children": [
                child.to_dict() if isinstance(child, JsonSerializable) else str(child)
                for child in self.children
            ],
        }


class RequirementAbstractSyntaxTree(JsonSerializable):
    def __init__(self, root: Union[Node, Leaf]):
        self.root = root

    @classmethod
    def from_json(cls, json_data):
        if isinstance(json_data, dict):
            return cls(Node.from_json(json_data))
        elif isinstance(json_data, str):
            return cls(Leaf(json_data))
        else:
            return None

    def to_dict(self):
        return (
            self.root.to_dict()
            if isinstance(self.root, JsonSerializable)
            else str(self.root)
        )


class RequirementParser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> RequirementAbstractSyntaxTree:
        root = self.parse_or()
        return RequirementAbstractSyntaxTree(root)

    def parse_or(self):
        children = [self.parse_and()]
        while self._peek_kind() == "OR":
            self.pos += 1
            children.append(self.parse_and())
        return children[0] if len(children) == 1 else Node("OR", children)

    def parse_and(self):
        children = [self.parse_primary()]

        while True:
            kind = self._peek_kind()
            if kind == "AND":
                self.pos += 1
                children.append(self.parse_primary())
            elif kind in ("TEXT", "COURSE", "LPAREN"):
                children.append(self.parse_primary())
            else:
                break

        return children[0] if len(children) == 1 else Node("AND", children)

    def parse_primary(self):
        kind = self._peek_kind()

        if kind == "LPAREN":
            self.pos += 1
            node = self.parse_or()
            if self._peek_kind() != "RPAREN":
                raise SyntaxError("Expected ')'")
            self.pos += 1
            return node

        if kind in ("TEXT", "COURSE"):
            _, val = self.tokens[self.pos]
            self.pos += 1
            return Leaf(val)

        if kind == "EOF":
            return Leaf("")

        raise SyntaxError(f"Unexpected token {kind!r}")

    def _peek_kind(self):
        return self.tokens[self.pos][0] if self.pos < len(self.tokens) else "EOF"
