import argparse
import logging
import re
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import timezone
from datetime import tzinfo

import arxiv
from pandas.tseries.offsets import BusinessDay
from slackweb import Slack
from tenacity import retry
from tenacity import stop_after_attempt
from tenacity import wait_fixed

__version__ = "0.0.35"

UTC = timezone.utc
JST = timezone(timedelta(hours=9), "JST")
EST = timezone(timedelta(hours=-5), "EST")


def _truncate_authors(authors: list, limit=2) -> list:
    return authors if len(authors) <= limit else authors[:limit] + ["..."]


def _arxiv_url_to_id(url: str) -> str:
    return re.match(r"http\://arxiv\.org/abs/(\d{4}\.\d{5})[v\d+]?", url).group(1)


def latest_announced_date(now: datetime) -> datetime:
    """
    Ignores summer time

    >>> now = datetime(2021, 1, 11, 8, 0, tzinfo=JST)
    >>> latest_announced_date(now).astimezone(JST).isoformat()
    '2021-01-08T10:00:00+09:00'

    >>> now = datetime(2021, 1, 12, 8, 0, tzinfo=JST)
    >>> latest_announced_date(now).astimezone(JST).isoformat()
    '2021-01-11T10:00:00+09:00'

    >>> now = datetime(2021, 1, 13, 8, 0, tzinfo=JST)
    >>> latest_announced_date(now).astimezone(JST).isoformat()
    '2021-01-12T10:00:00+09:00'

    >>> now = datetime(2021, 1, 14, 8, 0, tzinfo=JST)
    >>> latest_announced_date(now).astimezone(JST).isoformat()
    '2021-01-13T10:00:00+09:00'

    >>> now = datetime(2021, 1, 15, 8, 0, tzinfo=JST)
    >>> latest_announced_date(now).astimezone(JST).isoformat()
    '2021-01-14T10:00:00+09:00'
    """
    d = now.astimezone(EST)
    if d.time() < time(20, 0):
        d -= timedelta(days=1)
    while d.isoweekday() in (5, 6):  # Fri or Sat -> Thu
        d -= timedelta(days=1)
    return datetime(d.year, d.month, d.day, 20, 0, tzinfo=EST)


def get_submitted_date_range(announced_date: date) -> (datetime, datetime):
    """
    Get the submitted date ranges of the papers which are announced at
    20:00 of `annouced_date` (EST).

    cf.
    https://arxiv.org/help/availability

    Returns
    -------
    (submitted_date_begin: date, submitted_date_end: date)

    Examples
    --------
    >>> fmt = lambda b, e: (b.astimezone(EST).isoformat(), e.astimezone(EST).isoformat())

    >>> b, e = get_submitted_date_range(date(2021, 1, 12))
    >>> fmt(b, e)
    ('2021-01-11T14:00:00-05:00', '2021-01-12T13:59:59-05:00')

    >>> b, e = get_submitted_date_range(date(2021, 1, 13))
    >>> fmt(b, e)
    ('2021-01-12T14:00:00-05:00', '2021-01-13T13:59:59-05:00')

    >>> b, e = get_submitted_date_range(date(2021, 1, 14))
    >>> fmt(b, e)
    ('2021-01-13T14:00:00-05:00', '2021-01-14T13:59:59-05:00')

    >>> b, e = get_submitted_date_range(date(2021, 1, 17))
    >>> fmt(b, e)
    ('2021-01-16T14:00:00-05:00', '2021-01-17T13:59:59-05:00')

    >>> b, e = get_submitted_date_range(date(2021, 1, 18))
    >>> fmt(b, e)
    ('2021-01-15T14:00:00-05:00', '2021-01-18T13:59:59-05:00')
    """
    if announced_date.isoweekday() in (5, 6):
        raise ValueError

    if announced_date.isoweekday() != 1:
        b = announced_date - timedelta(1)
        e = announced_date
    else:
        b = announced_date - timedelta(3)
        e = announced_date

    datetime_b = datetime(b.year, b.month, b.day, 14, 0, 0, tzinfo=EST)
    datetime_e = datetime(e.year, e.month, e.day, 13, 59, 59, tzinfo=EST)

    return (datetime_b, datetime_e)


@retry(wait=wait_fixed(30), stop=stop_after_attempt(10))
def fetch_paper_feeds(category, from_datetime, to_datetime) -> list:
    """
    Fetch paper feeds in the specified category and date.

    Parameters
    ----------
    - category : str
        Subject category to search.
    - from_datetime : datetime
    - to_datetime : datetime

    Returns
    -------
    feeds : list[FeedParserDict]
        Feeds of arXiv articles.
    """
    b, e = from_datetime.strftime("%Y%m%d%H%M%S"), to_datetime.strftime("%Y%m%d%H%M%S")
    query = f"cat:{category} AND submittedDate:[{b} TO {e}]"
    logging.info(f"arXiv query: {query}")
    feeds = arxiv.query(query, sort_by="submittedDate", max_results=1000)

    # Remove cross-lists
    feeds = filter(
        lambda feed: re.match(category, feed.arxiv_primary_category["term"]), feeds
    )
    return feeds


def feed_to_post(feed) -> str:
    """
    Returns Slack post to describe the given paper feed.

    Parameters
    ----------
    - feed : FeedParserDict
        Feed of an arXiv article.

    Returns
    -------
    post : str
        Slack post.
    """
    url = feed.arxiv_url
    identifier = _arxiv_url_to_id(url)
    title = feed.title.replace("\n", "").replace("  ", " ")
    authors = ", ".join(_truncate_authors(feed.authors, 2))
    return f"[<{url}|{identifier}>] {title} ({authors})"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--category", required=True, help="query to specify category"
    )
    parser.add_argument(
        "-d", "--date", required=False, help="current UTC time in ISO format"
    )
    parser.add_argument("-w", "--webhook", required=False, help="Slack webhook URL")
    args = parser.parse_args()

    logging.info(f"version: {__version__}")
    logging.info(f"Current datetime: {datetime.now(tz=UTC)}")
    logging.info(f"Current datetime: {datetime.now(tz=JST)}")

    if args.date is None:
        posted_date = datetime.now(timezone.utc)
    else:
        posted_date = datetime.fromisoformat(args.date + "+00:00")

    announced_date = latest_announced_date(posted_date)
    from_datetime, to_datetime = get_submitted_date_range(announced_date)

    logging.info(f"Posted datetime: {posted_date.astimezone(UTC)}")
    logging.info(f"Posted datetime: {posted_date.astimezone(JST)}")
    logging.info(f"Announced datetime: {announced_date.astimezone(UTC)}")
    logging.info(f"Announced datetime: {announced_date.astimezone(JST)}")
    logging.info(
        f"Submitted datetime: {from_datetime.astimezone(UTC)}-{to_datetime.astimezone(UTC)}"
    )
    logging.info(
        f"Submitted datetime: {from_datetime.astimezone(JST)}-{to_datetime.astimezone(JST)}"
    )

    post = f"New submissions for {announced_date.astimezone(JST).date().isoformat()}"
    logging.info(f"Post: {post}")
    if args.webhook is not None:
        response = Slack(url=args.webhook).notify(text=post)
        logging.info(f"Response: {response}")

    for feed in fetch_paper_feeds(args.category, from_datetime, to_datetime):
        post = feed_to_post(feed)
        logging.info(f"Post: {post}")
        if args.webhook is not None:
            response = Slack(url=args.webhook).notify(text=post)
            logging.info(f"Response: {response}")
