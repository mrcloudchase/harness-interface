// An example hook from the harness folder: pi loads every extension in ~/.pi/agent/extensions/, and this
// one says so before each run starts (in RPC mode a notification is an `extension_ui_request` on stdout).
export default function (pi: any) {
  pi.on("before_agent_start", async (_event: any, ctx: any) => {
    ctx.ui.notify("hi-live-hook", "info");
  });
}
