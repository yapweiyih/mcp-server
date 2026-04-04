import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ER Query Agent – CopilotKit UI",
  description: "Expert Request query assistant powered by ADK + AG-UI + CopilotKit",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
