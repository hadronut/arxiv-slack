import argparse
import datetime
import logging
import re

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


@retry(wait=wait_fixed(60), stop=stop_after_attempt(5))
def fetch_paper_feeds(category: str, date: datetime.date) -> list:
    """
    Fetch paper feeds in the specified category and date.

    Parameters
    ----------
    - category : str
        Subject category to search.
    - date : datetime.date
        Date to search articles.

    Returns
    -------
    feeds : list[FeedParserDict]
        Feeds of arXiv articles.
    """
    yyyymmdd = date.strftime("%Y%m%d")
    query = f"cat:{category} AND submittedDate:[{yyyymmdd}000000 TO {yyyymmdd}235959]"
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
    parser.add_argument("-w", "--webhook", required=True)
    parser.add_argument("-c", "--category", required=True)
    parser.add_argument("-d", "--delay", default=2, type=int)
    args = parser.parse_args()

    # Note: arXiv API has a one-day delay
    date = datetime.date.today() - BDay(args.delay)

    for feed in fetch_paper_feeds(category=args.category, date=date):
        notify_slack(feed_to_post(feed), args.webhook)
