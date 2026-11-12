// Faces only the polarized mode uses; loaded on demand (see main.ts) so the garden mode
// never pays for their @font-face tables. Each face downloads only when rendered.
// Noto Sans SC 900 / 200 give the weight-contrast titles, 300 the light descriptions.
import "@fontsource/noto-sans-sc/200.css";
import "@fontsource/noto-sans-sc/300.css";
import "@fontsource/noto-sans-sc/900.css";
// Latin display (Unbounded 200 is the thin numeral face of the prototype)
import "@fontsource/unbounded/200.css";
import "@fontsource/unbounded/300.css";
import "@fontsource/unbounded/400.css";
import "@fontsource/unbounded/600.css";
// readouts, codes, tick labels
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
