"""Scrapy integration. Successful responses survive process interruption."""

import gzip
import hashlib
import json
import uuid

from scrapy import signals
from scrapy.crawler import CrawlerProcess
from scrapy.http import Response
from scrapy.utils.request import fingerprint

from sqlalchemy import select, delete
from sqlalchemy.dialects.sqlite import insert

from .schema import responses
from .store import Store, now


class ArchiveMiddleware:
    def __init__(self, crawler):
        self.crawler = crawler
        self.store = crawler.pipeline_store
        self.run = crawler.settings.get("PIPELINE_RUN")
        self.source = crawler.settings.get("PIPELINE_SOURCE")
        self.directory = self.store.root / "raw"
        self.directory.mkdir(exist_ok=True)
        crawler.signals.connect(self.failed, signal=signals.spider_error)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request):
        row = self.store.db.execute(
            select(responses).where(
                responses.c.run_id == self.run,
                responses.c.source == self.source,
                responses.c.fingerprint == fingerprint(request).hex(),
            ),
        ).fetchone()
        if row:
            body = gzip.decompress((self.directory / row["body_hash"]).read_bytes())
            if hashlib.sha256(body).hexdigest() != row["body_hash"]:
                raise ValueError("Archived response checksum mismatch")
            return Response(
                row["url"],
                status=row["status"],
                body=body,
                headers={"Content-Type": row["content_type"]},
                request=request,
                flags=["archived"],
            )
        if self.crawler.settings.getbool("PIPELINE_OFFLINE"):
            raise RuntimeError(f"No saved response for {request.url}")
        return None

    def process_response(self, request, response):
        if response.status == 200 and "archived" not in response.flags:
            body_hash = hashlib.sha256(response.body).hexdigest()
            path = self.directory / body_hash
            if not path.exists():
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(gzip.compress(response.body, mtime=0))
                temporary.replace(path)
            with self.store.db:
                self.store.db.execute(
                    insert(responses)
                    .values(
                        run_id=self.run,
                        source=self.source,
                        fingerprint=fingerprint(request).hex(),
                        url=response.url,
                        status=response.status,
                        content_type=response.headers.get(
                            "Content-Type", b"application/octet-stream"
                        ).decode(),
                        body_hash=body_hash,
                        fetched_at=now(),
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            responses.c.run_id,
                            responses.c.source,
                            responses.c.fingerprint,
                        ],
                        set_={
                            "url": response.url,
                            "status": response.status,
                            "content_type": response.headers.get(
                                "Content-Type", b"application/octet-stream"
                            ).decode(),
                            "body_hash": body_hash,
                            "fetched_at": now(),
                        },
                    ),
                )
        return response

    def failed(self, failure, response, spider):
        # A parse failure may be an application-level error returned with HTTP 200.
        # Retry it from the origin on resume instead of permanently replaying it.
        with self.store.db:
            self.store.db.execute(
                delete(responses).where(
                    responses.c.run_id == self.run,
                    responses.c.source == self.source,
                    responses.c.fingerprint == fingerprint(response.request).hex(),
                ),
            )


class DatabasePipeline:
    @classmethod
    def from_crawler(cls, crawler):
        instance = cls()
        instance.store = crawler.pipeline_store
        instance.run = crawler.settings.get("PIPELINE_RUN")
        instance.source = crawler.settings.get("PIPELINE_SOURCE")
        return instance

    def process_item(self, item):
        try:
            self.store.put(self.run, self.source, item)
        except Exception:
            with self.store.db:
                self.store.db.execute(
                    delete(responses).where(
                        responses.c.run_id == self.run,
                        responses.c.source == self.source,
                        responses.c.url == item.get("source_url"),
                    ),
                )
            raise
        return item


def http_settings(config):
    limits = config.get("http", {})
    concurrent = limits.get("concurrency", 32)
    per_domain = limits.get("per_domain", 16)
    target = limits.get("target_concurrency", 8)
    delay = limits.get("download_delay", 0.1)
    if not (
        1 <= per_domain <= concurrent <= 128
        and 0 < target <= per_domain
        and 0 <= delay <= 60
    ):
        raise ValueError("Invalid HTTP concurrency or delay limits")
    return {
        "CONCURRENT_REQUESTS": concurrent,
        "CONCURRENT_REQUESTS_PER_DOMAIN": per_domain,
        "DOWNLOAD_DELAY": delay,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": max(delay, 0.1),
        "AUTOTHROTTLE_TARGET_CONCURRENCY": target,
        "AUTOTHROTTLE_MAX_DELAY": 60,
    }


def crawl(root, run, source, offline=False):
    from .spiders import SPIDERS

    store = Store(root)
    store.reset_source(run, source)
    from uwcourses.http_utils import get_user_agent

    config = json.loads(store.run(run)["config_json"])
    settings = {
        **http_settings(config),
        "USER_AGENT": json.loads(store.run(run)["config_json"]).get("user_agent")
        or get_user_agent(),
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_TIMEOUT": 60,
        "RETRY_TIMES": 4,
        "RETRY_HTTP_CODES": [408, 429, 500, 502, 503, 504],
        "TELNETCONSOLE_ENABLED": False,
        "COOKIES_ENABLED": False,
        "LOG_LEVEL": "INFO",
        "JOBDIR": str(store.root / "runs" / run / source / uuid.uuid4().hex),
        "PIPELINE_ROOT": str(store.root),
        "PIPELINE_RUN": run,
        "PIPELINE_SOURCE": source,
        "PIPELINE_OFFLINE": offline,
        "DOWNLOADER_MIDDLEWARES": {"uwcourses.crawl.ArchiveMiddleware": 560},
        "ITEM_PIPELINES": {"uwcourses.crawl.DatabasePipeline": 100},
    }
    process = CrawlerProcess(settings)
    crawler = process.create_crawler(SPIDERS[source])
    crawler.pipeline_store = store
    failures = []
    crawler.signals.connect(
        lambda **kwargs: failures.append("item validation failed"),
        signal=signals.item_error,
        weak=False,
    )
    deferred = process.crawl(crawler, store=store, run=run)
    deferred.addErrback(lambda failure: failures.append(str(failure.value)))
    process.start()
    stats = crawler.stats.get_stats()
    if (
        failures
        or stats.get("spider_exceptions/count", 0)
        or stats.get("log_count/ERROR", 0)
        or getattr(crawler.spider, "failures", 0)
    ):
        raise RuntimeError(f"{source} crawl failed; inspect its log and resume")
    if stats.get("finish_reason") != "finished" or not stats.get("item_scraped_count"):
        raise RuntimeError(f"{source} crawl did not finish with records")
    store.close()
