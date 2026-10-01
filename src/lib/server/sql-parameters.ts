export function sqlValues(values: readonly unknown[]) {
  return values.map((value) => {
    if (
      value === null ||
      typeof value === "string" ||
      (typeof value === "number" && Number.isFinite(value))
    )
      return value;
    throw new Error("Invalid SQL parameter");
  });
}
