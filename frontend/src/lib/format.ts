// Spanish typographic thousands: "3 407" with a non-breaking space, so the
// mono stat lines (sidebar corpus block, corpus drawer) never wrap mid-number
// and always format identically.
export function formatThousands(n: number): string {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}
