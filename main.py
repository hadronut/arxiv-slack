import argparse
import logging
import re
from datetime import date
from datetime import datetime

import arxiv
from pandas.tseries.offsets import BDay
from slackweb import Slack
from tenacity import retry
from tenacity import stop_after_attempt
from tenacity import wait_fixed


def _truncate_authors(authors: list, limit=2) -> list:
    return authors if len(authors) <= limit else authors[:limit] + ["..."]


def _arxiv_url_to_id(url: str) -> str:
    return re.match(r"http\://arxiv\.org/abs/(\d{4}\.\d{5})[v\d+]?", url).group(1)


def get_announced_date(posted_date: date, delay=1):
    """
    ...

    Parameters
    ----------
    - posted_date : date
        Posted date in UTC.

    Examples
    --------
    >>> get_announced_date(date(2020, 1, 5))   # Sun -> Thu
    Timestamp('2020-01-03 00:00:00')
    >>> get_announced_date(date(2020, 1, 6))   # Mon -> Fri
    Timestamp('2020-01-03 00:00:00')
    >>> get_announced_date(date(2020, 1, 7))   # Tue -> Mon
    Timestamp('2020-01-06 00:00:00')
    >>> get_announced_date(date(2020, 1, 8))   # Wed -> Tue
    Timestamp('2020-01-07 00:00:00')
    >>> get_announced_date(date(2020, 1, 9))   # Thu -> Wed
    Timestamp('2020-01-08 00:00:00')
    """
    if posted_date.isoweekday() == 0:
        # Sun -> Thu
        return posted_date - BDay(2)
    else:
        return posted_date - BDay(1)


def get_submitted_date_range(announced_date: date) -> (datetime, datetime):
    """
    https://arxiv.org/help/availability

    Parameters
    ----------
    - announced_date : date
        Announced date in UTC.

    Examples
    --------
    >>> get_submitted_date_range(date(2021, 1, 6))   # Wed -> Mon - Tue
    (datetime.datetime(2021, 1, 4, 18, 0), datetime.datetime(2021, 1, 5, 17, 59, 59))
    >>> get_submitted_date_range(date(2021, 1, 7))   # Thu -> Tue - Wed
    (datetime.datetime(2021, 1, 5, 18, 0), datetime.datetime(2021, 1, 6, 17, 59, 59))
    >>> get_submitted_date_range(date(2021, 1, 8))   # Fri -> Wed - Thu
    (datetime.datetime(2021, 1, 6, 18, 0), datetime.datetime(2021, 1, 7, 17, 59, 59))
    >>> get_submitted_date_range(date(2021, 1, 11))   # Mon -> Thu - Fri
    (datetime.datetime(2021, 1, 7, 18, 0), datetime.datetime(2021, 1, 8, 17, 59, 59))
    >>> get_submitted_date_range(date(2021, 1, 12))   # Tue -> Fri - Mon
    (datetime.datetime(2021, 1, 8, 18, 0), datetime.datetime(2021, 1, 11, 17, 59, 59))
    """
    if announced_date.isoweekday() in (0, 6):
        raise RuntimeWarning("announced_date is weekend")

    b = announced_date - BDay(2)
    e = announced_date - BDay(1)
    datetime_b = datetime(b.year, b.month, b.day, 18, 0, 0)
    datetime_e = datetime(e.year, e.month, e.day, 17, 59, 59)

    return (datetime_b, datetime_e)


@retry(wait=wait_fixed(1), stop=stop_after_attempt(5))
def fetch_paper_feeds(category: str, announced_date: date) -> list:
    """
    Fetch paper feeds in the specified category and date.

    Parameters
    ----------
    - category : str
        Subject category to search.
    - announced_date : date
        Date to search articles.

    Returns
    -------
    feeds : list[FeedParserDict]
        Feeds of arXiv articles.
    """
    b, e = get_submitted_date_range(announced_date)

    query = f"cat:{category} AND submittedDate:[{b.strftime('%Y%m%d%H%M%S')} TO {e.strftime('%Y%m%d%H%M%S')}]"
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


@retry(wait=wait_fixed(60), stop=stop_after_attempt(5))
def notify_slack(text: str, url: str):
    """
    Notify slack the given text.

    Parameters
    ----------
    - text : str
        Text to notify.
    - url: str
        The name of the environment variale that stores the incoming webhook URL.
        Caution: This URL is confidential. Do not compromise it.
    """
    logging.info(f"Slack: {text}")
    Slack(url=url).notify(text=text)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--date", required=True)
    parser.add_argument("-w", "--webhook", required=True)
    parser.add_argument("-c", "--category", required=True)
    args = parser.parse_args()

    posted_date = datetime.strptime(args.date, "%Y%m%d")
    announced_date = get_announced_date(posted_date)

    for feed in fetch_paper_feeds(args.category, announced_date):
        notify_slack(feed_to_post(feed), args.webhook)
