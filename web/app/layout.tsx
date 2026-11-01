import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "ORACLE | Private Console", description: "Private ORACLE research and paper execution console" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
