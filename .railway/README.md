# Railway Infrastructure as Code

This directory mirrors the production Railway project at a project level.

Use Railway CLI with the linked production project:

```bash
railway config plan
railway config apply
```

Always inspect the plan before applying. Existing secret/resource-reference variables are kept with `preserve()`.

The production PostgreSQL database and private storage bucket already exist. Do not accept a plan that proposes deleting or replacing either resource.
