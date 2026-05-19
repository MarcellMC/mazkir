import { NodeSDK } from "@opentelemetry/sdk-node";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-proto";
import { getNodeAutoInstrumentations } from "@opentelemetry/auto-instrumentations-node";
import { Resource } from "@opentelemetry/resources";
import { ATTR_SERVICE_NAME } from "@opentelemetry/semantic-conventions";

const endpoint =
  process.env.OTEL_EXPORTER_OTLP_ENDPOINT ?? "http://localhost:6006/v1/traces";
const serviceName = process.env.OTEL_SERVICE_NAME ?? "telegram-bot";

const sdk = new NodeSDK({
  resource: new Resource({
    [ATTR_SERVICE_NAME]: serviceName,
    "openinference.project.name": "mazkir",
  }),
  traceExporter: new OTLPTraceExporter({ url: endpoint }),
  instrumentations: [
    getNodeAutoInstrumentations({
      "@opentelemetry/instrumentation-fs": { enabled: false },
    }),
  ],
});

try {
  sdk.start();
} catch (err) {
  // eslint-disable-next-line no-console
  console.error("tracing_init_failed", err);
}

export { sdk };
