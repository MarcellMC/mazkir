import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import pino from "pino";

const logsDir =
  process.env.LOGS_DIR ?? resolve(process.cwd(), "..", "..", "data", "logs");
const logFile = `${logsDir}/telegram-bot.jsonl`;

mkdirSync(logsDir, { recursive: true });
mkdirSync(dirname(logFile), { recursive: true });

const level = process.env.LOG_LEVEL ?? "info";

export const logger = pino(
  {
    level,
    base: { service: "telegram-bot" },
    timestamp: () => `,"ts":"${new Date().toISOString()}"`,
  },
  pino.multistream([
    { stream: process.stdout },
    { stream: pino.destination({ dest: logFile, mkdir: true, sync: false }) },
  ]),
);
