import type { Metadata } from "next";
import { Geist } from "next/font/google";
import { ThemeProvider } from "@/context/theme";
import "./globals.css";

const geist = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AgenticHire AI",
  description: "Autonomous multi-agent job application system",
};

const themeBootstrapScript = `
(function() {
  try {
    var t = localStorage.getItem("theme");
    if (t !== "light" && t !== "dark" && t !== "cyberpunk") {
      t = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    document.documentElement.setAttribute("data-theme", t);
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geist.variable} h-full`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrapScript }} />
      </head>
      <body className="min-h-full">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
