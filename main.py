import datetime
import os
import re

import arxiv
import yaml
from slackweb import Slack


def _truncate_authors(authors: list, limit=2) -> list:
    return authors if len(authors) <= limit else authors[:limit] + ["..."]


def _arxiv_url_to_id(url: str) -> str:
    return re.match(r"http\://arxiv\.org/abs/(\d{4}\.\d{5})[v\d+]?", url).group(1)


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
    feeds = arxiv.query(
        f"cat:{category} AND submittedDate:[{yyyymmdd}000000 TO {yyyymmdd}235959]",
        sort_by="submittedDate",
    )
    # Remove cross-lists
    feeds = filter(lambda feed: feed.arxiv_primary_category["term"] == category, feeds)
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


def notify_slack(text: str, webhook_url_name: str):
    """
    Notify slack the given text.

    Parameters
    ----------
    - text : str
        Text to notify.
    - webhook_url_name : str
        The name of the environment variale that stores the incoming webhook URL.
    """
    # The content of __webhook_url is confidential.  Do not compromise it.
    __webhook_url = os.getenv(webhook_url_name)
    if __webhook_url is None:
        raise ValueError(f"{webhook_url_name} not found in env variable")
    Slack(url=__webhook_url).notify(text=text)


if __name__ == "__main__":
    date = datetime.date.today() - datetime.timedelta(days=2)
    config_file = os.path.dirname(os.path.abspath(__file__)) + "/config.yml"

    with open(config_file) as f:
        # `config` is something like:
        # [{'category': 'hep-th', 'webhook_url_name': 'WEBHOOK_HEP_TH'},
        #  {'category': 'hep-ph', 'webhook_url_name': 'WEBHOOK_HEP_PH'}]
        config = yaml.load(f, Loader=yaml.SafeLoader)

    for item in config:
        for feed in fetch_paper_feeds(category=item["category"], date=date):
            notify_slack(feed_to_post(feed), item["webhook_url_name"])
