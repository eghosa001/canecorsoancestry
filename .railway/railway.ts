import {
  bucket,
  defineRailway,
  github,
  postgres,
  preserve,
  project,
  service,
} from "railway/iac";

export default defineRailway((ctx) => {
  const production = ctx.environment === "production";

  const database = postgres("Postgres");
  const media = bucket("dog-evidence-bucket", { region: "sjc" });

  const web = service("web", {
    source: github("eghosa001/canecorsoancestry", { branch: "main" }),
    build: "python manage.py collectstatic --noinput",
    start:
      "python manage.py collectstatic --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 60 --access-logfile - --error-logfile -",
    preDeploy: "python manage.py migrate --noinput",
    healthcheck: "/healthz/",
    healthcheckTimeout: 60,
    // Current Railway plan allows one custom domain per service.
    // Serve the apex directly; redirect www at the DNS/CDN layer.
    domains: production ? ["canecorsoancestry.com"] : [],
    env: {
      DJANGO_SETTINGS_MODULE: "config.settings.production",
      DJANGO_SECRET_KEY: preserve(),
      DATABASE_URL: database.env.DATABASE_URL,
      DJANGO_REQUIRE_OBJECT_STORAGE: "1",
      BUCKET: preserve(),
      REGION: preserve(),
      ENDPOINT: preserve(),
      AWS_ACCESS_KEY_ID: preserve(),
      AWS_SECRET_ACCESS_KEY: preserve(),
      SITE_URL: "https://canecorsoancestry.com",
      DJANGO_ALLOWED_HOSTS:
        "canecorsoancestry.com,www.canecorsoancestry.com,healthcheck.railway.app,.up.railway.app,.railway.internal,localhost,127.0.0.1",
      DJANGO_CSRF_TRUSTED_ORIGINS:
        "https://canecorsoancestry.com,https://www.canecorsoancestry.com,https://*.up.railway.app",
      DJANGO_HSTS_SECONDS: "3600",
      DJANGO_HSTS_INCLUDE_SUBDOMAINS: "1",
      DJANGO_HSTS_PRELOAD: "0",
      DJANGO_LOG_LEVEL: "INFO",
      ANCESTRY_EMAIL_NOTIFICATIONS: "0",
      DEFAULT_FROM_EMAIL:
        "Cane Corso Ancestry <noreply@canecorsoancestry.com>",
      EMAIL_BACKEND: "django.core.mail.backends.smtp.EmailBackend",
      EMAIL_HOST: "smtp.resend.com",
      EMAIL_PORT: "587",
      EMAIL_HOST_USER: "resend",
      EMAIL_USE_TLS: "1",
      EMAIL_TIMEOUT: "10",
      SENTRY_ENVIRONMENT: "production",
      SENTRY_TRACES_SAMPLE_RATE: "0.05",
    },
  });

  return project("Cane Corso Ancestry", {
    resources: [database, media, web],
  });
});
