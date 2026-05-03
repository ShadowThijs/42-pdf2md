"""Configuration constants for 42 PDF parsing."""

# Color codes (hex integers as returned by PyMuPDF)
COLOR_PURPLE = 0x800080    # ● section heading bullet
COLOR_GREEN = 0x008000     # ✓ Good practice
COLOR_RED = 0xB30000       # ✗ Bad practice
COLOR_LIGHT_GRAY = 0xF2F2F2  # Code block text (light on dark bg)

# Font size thresholds (points)
SIZE_CHAPTER = 22.0       # >= 22.0 => chapter heading (~24.8pt)
SIZE_SUBSECTION = 15.0    # >= 15.0 and < SIZE_CHAPTER => subsection (~17.2pt)
SIZE_BODY = 11.0          # >= 11.0 and < SIZE_SUBSECTION => body text (~12pt)

# Y-coordinate thresholds for header/footer detection
Y_HEADER_MAX = 55.0
Y_FOOTER_MIN = 780.0

# X-coordinate thresholds for indentation
X_BODY = 72.0
X_BULLET = 89.0
X_SUB_BULLET = 115.0

# Y-coordinate grouping tolerance for line detection
LINE_Y_TOLERANCE = 3.0

# Font name substrings for classification
FONT_DINGBATS = "Dingbats"
FONT_MATH_SYMBOLS = "LMMathSymbols"
FONT_MONO = "LMMono"
