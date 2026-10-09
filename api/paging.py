"""
Optional paging on the list routes: `limit` and `offset` in, `X-Total-Count` out.

The body stays the plain JSON list it always was, so a client that sends
neither parameter sees no change. One that sends either gets the size of the
whole list in the header, at the cost of a COUNT query it asked for.
"""

from fastapi import Query, Request, Response

from meshbee_core.paging import Page, Paging

TOTAL_HEADER = "X-Total-Count"


def paging_query(
    default_limit: int | None = None, max_limit: int = 1000, what: str = "elementi"
):
    """
    A dependency reading `limit` and `offset` into a `Paging`.

    `default_limit` None makes `limit` optional: unset is the whole list, as the
    route returned before paging existed. A route that already capped its list
    passes its old default and maximum, which stay as they were.
    """
    limit_type = int if default_limit is not None else int | None

    def dependency(
        request: Request,
        limit: limit_type = Query(
            default_limit, ge=1, le=max_limit, description=f"Numero massimo di {what}"
        ),
        offset: int = Query(
            0, ge=0, description=f"{what.capitalize()} da saltare, per la paginazione"
        ),
    ) -> Paging:
        asked = "limit" in request.query_params or "offset" in request.query_params
        return Paging(limit=limit, offset=offset, total=asked)

    return dependency


def page_items(response: Response, page: Page) -> list:
    """The page's rows as the body; its total, when counted, as the header."""
    if page.total is not None:
        response.headers[TOTAL_HEADER] = str(page.total)
    return page.items
