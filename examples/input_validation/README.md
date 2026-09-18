# Input validation

Reject user text at the edge of your backend, before it reaches storage or other users.

```bash
pip install jevmod && jevmod init
uvicorn examples.input_validation.fastapi_dependency:app --port 8000     # POST /comments
python examples/input_validation/pydantic_validator.py                    # a ModeratedText field type
```

- `fastapi_dependency.py`: `moderated` is a dependency that judges the request body and answers `422` with the
  category and probability when it triggers. `POST /comments` uses it; the route body stays clean.
- `pydantic_validator.py`: `ModeratedText` is an `Annotated[str, AfterValidator(...)]`; any model field typed with
  it is judged on construction and raises `ValidationError` on a hit. Works in FastAPI bodies, settings, anywhere.

Both use one module-level `Moderator`, so repeated text is served from its cache and never re-sent. Batch when
you can: judging one field per request costs one Jev call each; `check_many` on a list costs one call total.

An Express middleware for Node lives in the npm package (`packages/jevmod-js`).
