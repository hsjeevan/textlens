export const THEME_NAMES: Record<string, string> = {
  customer_experience: "Customer experience",
  billing_pricing: "Billing & pricing",
  network_connectivity: "Network & connectivity",
  technology_product: "Technology & product",
  business_finance: "Business & finance",
};

export function themeName(key: string): string {
  if (THEME_NAMES[key]) return THEME_NAMES[key];
  const spaced = key.replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}

/** Like Python's f"{x:+.2f}". */
export const signed = (x: number, digits = 2) => (x >= 0 ? "+" : "") + x.toFixed(digits);

/** Like Python's f"{i:02d}". */
export const pad2 = (i: number) => String(i).padStart(2, "0");

export const thousands = (n: number) => n.toLocaleString("en-US");
