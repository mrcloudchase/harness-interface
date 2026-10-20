// An example plugin from the harness folder: OpenCode's hooks. Its `chat.message` hook runs on every
// prompt, before the model sees it, and prints its name, which the adapter passes on to stdout.
export const HiLiveHook = async () => ({
  "chat.message": async (input) => {
    console.log(`hi-live-hook: chat.message in ${input.sessionID}`)
  },
})
