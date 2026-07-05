/**
 * The C¹ mark, from export/citara-logo.svg. Glyphs are outlined <path>s (not
 * <text>), so the mark renders identically regardless of whether the IBM Plex
 * webfonts have loaded. Colors are --accent* vars (with the legal quartet as
 * literal fallback), so the tile tint, border and superscript follow the
 * active vertical; the C stays text-colored.
 */
export interface BrandMarkProps {
  size?: number
}

export function BrandMark({ size = 138 }: BrandMarkProps) {
  return (
    <svg
      viewBox="0 0 256 256"
      width={size}
      height={size}
      role="img"
      aria-label="Citara"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        {/* Unique id: colliding clipPath ids would clip one instance with
            another's geometry if the mark renders twice (welcome + sidebar). */}
        <clipPath id="citara-logo-clip">
          <rect x="1" y="1" width="254" height="254" rx="66.56" ry="66.56" />
        </clipPath>
      </defs>

      <g clipPath="url(#citara-logo-clip)">
        <rect
          x="0"
          y="0"
          width="256"
          height="256"
          fill="var(--accent-tint, rgba(124,156,255,0.13))"
        />
      </g>
      <rect
        x="1"
        y="1"
        width="254"
        height="254"
        rx="66.56"
        ry="66.56"
        fill="none"
        stroke="var(--accent-line, rgba(124,156,255,0.36))"
        strokeWidth="2"
      />

      <path
        fill="var(--text, #ECEEF2)"
        d="M133.15 189.80L133.15 189.80Q122.99 189.80 115.02 185.99Q107.04 182.18 101.47 175.40Q95.89 168.63 93.00 159.32Q90.11 150.00 90.11 138.99L90.11 138.99Q90.11 126.58 93.43 117.05Q96.74 107.52 102.39 101.03Q108.03 94.54 115.65 91.23Q123.27 87.91 131.74 87.91L131.74 87.91Q140.91 87.91 146.13 91.08Q151.36 94.26 153.33 97.93L153.33 97.93L154.04 97.93L154.04 89.60L168.57 89.60L168.57 120.23L154.04 120.23L154.04 113.59Q154.04 106.40 148.89 102.02Q143.73 97.65 134.42 97.65L134.42 97.65Q123.41 97.65 117.63 104.84Q111.84 112.04 111.84 125.16L111.84 125.16L111.84 150.43Q111.84 164.25 118.69 171.10Q125.53 177.94 136.82 177.94L136.82 177.94Q146.13 177.94 152.55 173.07Q158.98 168.21 162.22 160.16L162.22 160.16L169.42 164.25Q167.73 169.34 164.55 173.92Q161.37 178.51 156.79 182.04Q152.20 185.56 146.27 187.68Q140.35 189.80 133.15 189.80Z"
      />
      <path
        fill="var(--accent, #7C9CFF)"
        d="M187.98 93.26L167.61 93.26L167.61 88.73L175.74 88.73L175.74 67.73L175.36 67.73L168.93 75.35L165.45 72.43L172.78 63.71L181.29 63.71L181.29 88.73L187.98 88.73L187.98 93.26Z"
      />
    </svg>
  )
}
