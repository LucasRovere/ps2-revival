# General guidence
## 1. Don't be verbose

**Keep wording to a minimal. Be direct in your sentences. Keep very simple sentence structure. That makes it easier for everyone to keep up.**

## 2. Ask questions! If you run into an unresolved issue, stop and prompt the user.

# How we code

## 1. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 2. Focus in what was planned

**Define success criteria.**

Be sure to focus on the plan already made for that task:
- You have clear goals and steps for the task, stick to them
- Use the planned scope to define clearly the testing scope and be sure to create meaningful tests

The test: Every changed line should trace directly to the plan.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

## 4. Keep the patterns

**Something similar has probably already been done.**

We want the code to keep a consistent pattern to facilitate reading and maintaing
- Before working, check out the references provided in the planning


## 5. Minimal commenting and clean code

**Clean code should be readable by itself.**

Clean code should be readable by itself, no need to overcomment
- Only add comments when the code might be confusing
- Keep attention to naming. Good naming, generally serves the function of comments
- Be modular on the method level. A call method that calls a clear list of sub methods is a great way of keeping code readable. Ex:

```
class DeleteCompany
    def call
        pendencies = findCompanyPendencies()
        can_delete = resolveCompanyPendencies(pendencies)
        
        return delete_company() if can_delete
        mark_as_stuck_delete()
    end

    private

    ...
end
```


@AGENTS.md
