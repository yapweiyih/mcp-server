/**
 * Main page – ER Query Agent with CopilotKit chat UI.
 *
 * This demonstrates the simplest integration: a full-page chat panel
 * powered by CopilotKit that talks to the ADK agent via AG-UI protocol.
 *
 * Architecture:
 *   CopilotKit (React) → /api/copilotkit route → HttpAgent → ADK server (:8000/agui)
 */

"use client";

import { CopilotKit } from "@copilotkit/react-core";
import { CopilotChat } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";

export default function Home() {
  return (
    <CopilotKit runtimeUrl="/api/copilotkit">
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          height: "100vh",
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        }}
      >
        {/* Header */}
        <header
          style={{
            padding: "16px 24px",
            borderBottom: "1px solid #e0e0e0",
            background: "#4285F4",
            color: "white",
          }}
        >
          <h1 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 600 }}>
            🤖 ER Query Agent
          </h1>
          <p style={{ margin: "4px 0 0", fontSize: "0.85rem", opacity: 0.9 }}>
            Ask questions about Expert Requests • Powered by ADK + AG-UI +
            CopilotKit
          </p>
        </header>

        {/* Chat area */}
        <div style={{ flex: 1, overflow: "hidden" }}>
          <CopilotChat
            instructions="You are an Expert Request (ER) query assistant. Help users find information about Expert Requests."
            labels={{
              title: "ER Query Assistant",
              initial:
                "Hi! I can help you query Expert Requests. Try asking:\n\n" +
                '• "Find ERs assigned to user@google.com"\n' +
                '• "Show ERs from 2024"\n' +
                '• "Get details for ER-431059"\n' +
                '• "Submit a background task"',
            }}
          />
        </div>
      </div>
    </CopilotKit>
  );
}
