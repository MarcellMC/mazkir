import { Composer, InlineKeyboard } from "grammy";
import { config } from "../config.js";

export const startCommand = new Composer();

startCommand.command("start", async (ctx) => {
  const kb = new InlineKeyboard().webApp("🚀 Open App", config.webappUrl);

  await ctx.reply(
    [
      "👋 <b>Welcome to Mazkir!</b>",
      "",
      "Your personal assistant for tasks, habits, and goals.",
      "",
      "Quick commands:",
      "/day — Today's summary",
      "/tasks — Active tasks",
      "/habits — Habit tracker",
      "/goals — Goals & progress",
      "/tokens — Token balance",
      "/calendar — Today's schedule",
      "",
      "Or just type naturally: <i>\"I completed gym\"</i>",
    ].join("\n"),
    { parse_mode: "HTML", reply_markup: kb }
  );
});
