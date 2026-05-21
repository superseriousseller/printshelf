# PrintShelf seeding

`seed_user.py` populates a PrintShelf user (printers, filaments, prints)
from a YAML file. Used to bootstrap `/u/cam` before the Reddit launch.

## Workflow

1. **Upload photos to R2** — drag 15 print photos into your Cloudflare R2
   bucket via the dashboard. Note the public URL pattern (e.g.
   `https://cdn.printshelf.app/<filename>`).

2. **Copy the template**

   ```bash
   cp seed/cam.template.yaml seed/cam.yaml
   ```

   `seed/cam.yaml` is gitignored — safe to put real email/password in.

3. **Fill the YAML** — `user`, `printers`, `filaments`, `prints` sections.
   Each print references a printer by name and filaments by key.

4. **Dry-run** to spot typos:

   ```bash
   python backend/scripts/seed_user.py --config seed/cam.yaml --dry-run
   ```

5. **Seed against staging first**:

   ```bash
   python backend/scripts/seed_user.py --config seed/cam.yaml \
          --base https://staging.printshelf.app
   ```

   Visit `https://staging.printshelf.app/u/cam`. If the wall looks good,
   re-run against production.

6. **Seed production**:

   ```bash
   python backend/scripts/seed_user.py --config seed/cam.yaml \
          --base https://printshelf.app
   ```

## Idempotency

- User: registered the first time; subsequent runs log in with the same
  email/password.
- Printers: de-duped by name.
- Filaments: de-duped by (brand, material, color_name).
- Prints: **NOT** de-duped — re-running creates duplicates. Treat this as
  one-shot seeding; clear prints in the API before re-running.

## Output

On success the script prints the user's API key (use it for the Chrome
extension) and the public profile URL.
