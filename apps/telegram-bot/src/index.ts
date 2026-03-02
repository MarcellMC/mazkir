import { bot } from "./bot.js";

async function main() {
  console.log("Starting Mazkir bot...");
  const me = await bot.api.getMe();
  console.log(`Bot started as @${me.username}`);
  bot.start();
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
