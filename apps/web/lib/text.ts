/** Lowercase, without diacritics (đ included), punctuation collapsed to single spaces. */
export function fold(text: string): string {
  return text
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

const VIETNAMESE = /[ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ]/i;

/** "vi" when the text has Vietnamese letters, else "en": the language an answer is written in. */
export function langOf(text: string): "vi" | "en" {
  return VIETNAMESE.test(text) ? "vi" : "en";
}
