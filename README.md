# Second Brain

A private, markdown-first knowledge system for raw sources and generated wiki knowledge.

## Create your Second Brain from this template

> **Template setup only:** After initialization, remove this entire section from your new repository's README. Keep the sections below as documentation for your instance.

1. On this repository's GitHub page, select **Use this template**, then **Create a new repository**.
2. Choose an owner and repository name. Select **Private** if your knowledge base will contain personal information, then create the repository.
3. Clone your new repository and open its directory:

   ```sh
   git clone https://github.com/<owner>/<repository>.git
   cd <repository>
   ```

4. Install the dependencies described in **Manual CLI** below. Review and customize `SCHEMA.md` and `index.md` for your own workflow.
5. Remove this **Create your Second Brain from this template** section from the new instance's README, then commit your changes.

## Layout

- `inbox/` - temporary captures
- `raw/` - immutable Markdown sources
- `raw/assets/` - image assets
- `wiki/` - generated and maintained knowledge
- `wiki/collections/` - reading lists, habits, projects, and other collections
- `wiki/output/` - reports and exports
- `index.md` - content-oriented wiki catalog
- `log.md` - chronological operation log
- `SCHEMA.md` - maintained agent/user operating contract

## Using Copilot

Open this repository in a Copilot agent session and ask naturally. Copilot can select the repository's skills when relevant:

- "Ingest the article at this URL and add its key ideas to my wiki."
- "What have I learned about caching? Cite my sources."
- "Check my knowledge base for broken links and stale sources."
- "Log a task to review the design" or "Process today's journal."

You can also request `/ingest`, `/query`, `/lint`, or `/log` by name in your prompt. Skills guide Copilot through the work; they do not hide tool activity or automatically perform OCR. If the skills are not available in a current Copilot CLI session, restart it or use `/skills reload`. For a new journal capture, the `/log` skill keeps its original in the Git-ignored `inbox/`; removing that original can produce a source-drift warning.

### Weekend reminders

Ask Copilot to use `/weekend-reminders`, or use these prompts with a scheduling host that supports them:

- **Friday at 4 PM, local time:** "Give me my Friday weekend preview using `/weekend-reminders`."
- **Weekdays at 8 AM, local time:** "Give me my first-workday reminder using `/weekend-reminders`; skip other days."

Provide your time zone, usual workdays, holidays or days off, and an authorized calendar if available. The Friday preview checks Monday and Tuesday and looks further ahead after a known long weekend; the morning check-in focuses on the first workday. Both include relevant unfinished tasks and one next action. You can ask to snooze or defer to a specific time; automatic snoozing requires a host that confirms it can schedule the follow-up.

These are reusable prompts, not preconfigured automations. Configure the schedules in your chosen host and check its delivery behavior. A host may only wake an active app session, so an 8 AM notification is **not guaranteed** if you log in later. Use a host that queues or retries missed runs at next login, or ask for the check-in manually. If delivery cannot be verified, a retry may repeat a reminder.

### Daily and periodic routines

Ask naturally, or use these skill names in a reusable host prompt:

- "Help me start a morning log." (`/morning-log`)
- "Help me plan today." (`/daily-plan`)
- "Let me capture a note from today." (`/evening-capture`)
- "Show me overdue tasks." (`/overdue-tasks`)
- "Remind me about upcoming events." (`/upcoming-events`)
- "Help me review my week." (`/weekly-review`)
- "Help me review tasks for monthly migration." (`/monthly-migration`)
- "Help me shut down for the day." (`/shutdown-check`)

These routines give one primary next action and can be skipped or deferred without changing task status. They use the knowledge base and any authorized calendar available; missing information is noted. Choose times, time zone, workdays, holidays, and prompts in your automation host, not this repository. No schedules or notifications are created by installing the skills, and missed-run and snooze behavior depends on the host. See the delivery limitations under **Weekend reminders**.

## Manual CLI

Install the required YAML and Markdown parsers, file locking, and optional MarkItDown conversion support:

```sh
pip install -r requirements.txt
```

For direct use without Copilot:

```sh
python tools/second_brain.py ingest <file-or-url>
python tools/second_brain.py query "term"
python tools/second_brain.py lint
```
