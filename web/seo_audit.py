"""Audit build-time SEO assets; SSR semantics are checked against HTTP in Playwright."""
import json
import struct
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, unquote
from xml.etree import ElementTree

root = Path('.svelte-kit/cloudflare')
ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
origin = 'https://uwcourses.com'
index = ElementTree.parse(root / 'sitemap.xml')
urls = []
shards = index.findall('s:sitemap', ns)
assert shards, 'Missing sitemap shards'
for shard in shards:
    datetime.fromisoformat(shard.find('s:lastmod', ns).text.replace('Z', '+00:00'))
    location = shard.find('s:loc', ns).text
    blog = location == origin + '/blog/sitemap.xml'
    assert blog or location.startswith(origin + '/sitemaps/')
    tree = ElementTree.parse(root / unquote(urlparse(location).path).lstrip('/'))
    for entry in tree.findall('s:url', ns):
        url = entry.find('s:loc', ns).text
        assert url.startswith(origin + '/') and '?' not in url
        assert not url.endswith(('.md', '.json'))
        lastmod = entry.find('s:lastmod', ns)
        priority = entry.find('s:priority', ns)
        changefreq = entry.find('s:changefreq', ns)
        # Blog entries use only applicable optional sitemap metadata.
        if not blog or lastmod is not None:
            datetime.fromisoformat(lastmod.text.replace('Z', '+00:00'))
        if not blog or priority is not None:
            assert 0 <= float(priority.text) <= 1
        if not blog or changefreq is not None:
            assert changefreq.text in ('weekly', 'monthly')
        urls.append(url)
assert len(set(urls)) == len(urls), 'Duplicate sitemap URLs'
manifest = json.loads((root / 'social/manifest.json').read_text())
paths = set()
for card in manifest:
    assert card['path'] not in paths
    paths.add(card['path'])
    image = root / unquote(card['path']).lstrip('/')
    header = image.read_bytes()[:24]
    assert header[:8] == b'\x89PNG\r\n\x1a\n', image
    assert struct.unpack('>II', header[16:24]) == (1200, 630), image
assert (root / '_worker.js').exists(), 'SSR Worker missing'
assert not (root / 'courses/COMPSCI_300.html').exists(), 'Course unexpectedly prerendered'
print(json.dumps({'sitemaps': len(shards), 'urls': len(urls), 'social_cards': len(paths), 'rendering': 'SSR; HTTP SEO checks run in Playwright'}))
