import colors from "tailwindcss/colors";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        slate: colors.stone, // gris chauds plutôt que bleutés
        brand: { 50: "#edf3f0", 100: "#d6e5de", 500: "#2d7a66", 600: "#1f5f4f", 700: "#174a3d" },
      },
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        serif: ["Charter", "Iowan Old Style", "Georgia", "Cambria", "Times New Roman", "serif"],
      },
    },
  },
  plugins: [],
};
