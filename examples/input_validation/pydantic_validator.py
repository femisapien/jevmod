"""`ModeratedText`: a str field type that is judged by jevmod when the model is built."""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ValidationError

from jevmod import Moderator

mod = Moderator()


def _moderate(text: str) -> str:
    d = mod.check(text)
    if d.action != "none":
        raise ValueError(f"rejected: {d.category} {d.probability:.2f}")
    return text


ModeratedText = Annotated[str, AfterValidator(_moderate)]


class Review(BaseModel):
    author: str
    body: ModeratedText


if __name__ == "__main__":
    print(Review(author="ana", body="Great headset, the mic is a bit quiet though."))
    try:
        Review(author="bot", body="DM me for cheap accounts, paypal only, no refunds")
    except ValidationError as exc:
        print("blocked:", exc.errors()[0]["msg"])
