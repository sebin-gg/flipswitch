### 1. System Architecture
The system consists of three components:
- **Team Chat Integration Layer**: This is responsible for connecting to the team chat (via Switch SDK or bot API). It listens for commands (`@architect`) and routes messages to the core agent.
- **Core Agent**: Processes chat inputs to parse architecture discussions, generates draft ADRs, and interacts with the team to refine the ADR. It leverages an LLM (like OpenAI GPT) for understanding context.
- **Persistence Layer**: Commits finalized ADRs to a Git repository under `docs/adr/`.

**Architecture Diagram**:
```
[Team Chat (Mattermost/Slack)] <--> [Switch SDK/Bot Interface] <--> [Core Agent] <--> [Git Repository (docs/adr/)]
```

---

### 2. Core Agent Implementation

#### Steps:
1. Use the Switch SDK (or Bot API) to configure a listener for `@architect`.
2. Parse discussions triggered by `@architect` (e.g., "Start ADR draft for X").
3. Draft core ADR sections with a template:
   - **Context**: Summarize the team's input.
   - **Decision**: Identify the proposed solution.
   - **Consequences**: Detail pros/cons and future impact.
4. Ask clarifying questions in chat to fill gaps (e.g., missing trade-offs).
5. Commit the finalized ADR as Markdown to `docs/adr/`.

#### Pseudocode:
```python
import switch_sdk, git
from llm_helper import generate_adr, get_clarifications

def on_message(event):
    if "@architect" in event.message:
        discussion = capture_discussion(event.thread)
        draft = generate_adr(discussion)
        clarifications = get_clarifications(draft)
        refined_draft = refine_with_team(clarifications)
        save_to_git("docs/adr/", refined_draft)

def save_to_git(path, content):
    repo = git.Repo('./repo')
    file_path = f"{path}ADR-{generate_id()}.md"
    with open(file_path, 'w') as f:
        f.write(content)
    repo.index.add([file_path])
    repo.index.commit(f"Add ADR: {file_path}")
```

---

### 3. Directory Structure

```
spec-adr-architect/
│
├── core/
│   ├── agent