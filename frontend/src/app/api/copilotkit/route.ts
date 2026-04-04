/**
 * CopilotKit Runtime API Route
 *
 * This Next.js API route acts as a bridge between the CopilotKit frontend
 * and the ADK agent backend. It uses the AG-UI protocol (via HttpAgent)
 * to communicate with the Python FastAPI server running on port 8000.
 *
 * Flow:
 *   Browser (CopilotKit) → this route → HttpAgent → ADK AG-UI server (:8000/agui)
 */

import {
  CopilotRuntime,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { HttpAgent } from "@ag-ui/client";

// The AG-UI endpoint of the Python ADK agent server
const AGENT_URL = process.env.AGENT_URL || "http://localhost:8000/agui";

const runtime = new CopilotRuntime({
  agents: {
    default: new HttpAgent({ url: AGENT_URL }),
  },
});

const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
  runtime,
  endpoint: "/api/copilotkit",
});

export const POST = handleRequest;
