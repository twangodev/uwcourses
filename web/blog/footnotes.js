/** @typedef {{ type: string, tagName?: string, value?: string, properties?: Record<string, any>, children?: Node[] }} Node */

/** Number Markdown footnotes, label navigation, and give repeated references unique IDs. */
export function blogFootnotes() {
  /** @param {Node} tree */
  return (tree) => {
    /** @type {Map<string, { number: number, refs: string[] }>} */
    const notes = new Map();
    /** @param {Node} node @param {(node: Node, parent?: Node) => void} visit @param {Node} [parent] */
    function walk(node, visit, parent) {
      visit(node, parent);
      for (const child of node.children || []) walk(child, visit, node);
    }
    /** @param {Node} node @param {string} name */
    const hasClass = (node, name) => node.properties?.className?.includes(name);
    walk(tree, (node, parent) => {
      if (node.tagName !== "a" || !hasClass(node, "footnote-ref") || !parent)
        return;
      const target = String(node.properties?.href).slice(1);
      if (!notes.has(target))
        notes.set(target, { number: notes.size + 1, refs: [] });
      const note = notes.get(target);
      if (!note) return;
      const id = `blog-fnref-${note.number}-${note.refs.length + 1}`;
      note.refs.push(id);
      parent.properties = { ...parent.properties, id };
      node.properties = {
        ...node.properties,
        href: `#blog-fn-${note.number}`,
        role: "doc-noteref",
        ariaLabel: `Footnote ${note.number}`,
      };
      node.children = [{ type: "text", value: String(note.number) }];
    });
    walk(tree, (node) => {
      if (hasClass(node, "footnotes")) {
        node.tagName = "section";
        node.properties = {
          ...node.properties,
          role: "doc-endnotes",
          ariaLabelledBy: "blog-footnotes",
        };
        node.children = [
          {
            type: "element",
            tagName: "h2",
            properties: { id: "blog-footnotes" },
            children: [{ type: "text", value: "Notes and sources" }],
          },
          ...(node.children || []).filter((child) => child.tagName !== "hr"),
        ];
      }
      const note = notes.get(String(node.properties?.id));
      if (node.tagName !== "li" || !note) return;
      node.properties = {
        ...node.properties,
        id: `blog-fn-${note.number}`,
        value: note.number,
        tabIndex: -1,
      };
      walk(node, (child) => {
        if (child.children)
          child.children = child.children.filter(
            (item) => !hasClass(item, "footnote-backref"),
          );
      });
      const last = node.children?.at(-1);
      const container = last?.tagName === "p" ? last : node;
      container.children ??= [];
      for (const [index, ref] of note.refs.entries()) {
        container.children.push(
          { type: "text", value: " " },
          {
            type: "element",
            tagName: "a",
            properties: {
              href: `#${ref}`,
              className: ["footnote-backref"],
              role: "doc-backlink",
              ariaLabel: `Back to reference ${index + 1} for footnote ${note.number}`,
            },
            children: [
              {
                type: "text",
                value: note.refs.length > 1 ? `↩${index + 1}` : "↩",
              },
            ],
          },
        );
      }
    });
  };
}
