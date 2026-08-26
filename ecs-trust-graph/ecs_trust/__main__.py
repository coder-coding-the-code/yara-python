from .api import app, create_app  # noqa: F401


def main() -> None:
    import uvicorn

    uvicorn.run("ecs_trust.api:app", host="0.0.0.0", port=8080, reload=False)


if __name__ == "__main__":
    main()
