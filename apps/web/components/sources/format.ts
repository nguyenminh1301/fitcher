// Sizes of source tables as the Sources page shows them: from the source's own statistics, so approximate.

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 ? Math.round(value) : Math.round(value * 10) / 10} ${units[unit]}`;
}

/** A lower-case table name for a file, as the api derives it: the stem with accents removed. */
export function tableNameOf(fileName: string): string {
  const stem = fileName.includes(".") ? fileName.slice(0, fileName.lastIndexOf(".")) : fileName;
  const folded = stem.replace(/đ/g, "d").replace(/Đ/g, "D").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const slug = folded.replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40).replace(/_+$/, "");
  if (!slug) return "data";
  return /^[a-z]/.test(slug) ? slug : `f_${slug}`.slice(0, 40);
}

/** The column types a file column can be loaded as; each also comes as Nullable. */
export const FILE_TYPES = [
  "String", "Int64", "UInt64", "Float64", "Decimal(18, 2)", "Bool", "Date", "DateTime64(6)",
];

export function typeOptions(current: string): string[] {
  const all = FILE_TYPES.flatMap((type) => [type, `Nullable(${type})`]);
  return all.includes(current) ? all : [current, ...all];
}
