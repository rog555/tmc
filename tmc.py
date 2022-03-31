#!/usr/bin/env python
import argparse
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
import jmespath
import json
import os
import requests
import sys
import textwrap
import time

EX = ThreadPoolExecutor(max_workers=5)

color = namedtuple('color', 'red green yellow blue bold endc none')(*[
    lambda s, u=c: '\033[%sm%s\033[0m' % (u, s)
    if (sys.platform != 'win32' and u != '') else s
    for c in '91,92,93,94,1,0,'.split(',')
])


PDQ_CONFIG = {
    'workspace-policies': {
        'headers': [
            'fullName.workspaceName', 'fullName.name',
            'spec.type', 'spec.recipe'
        ],
        'api_join': {
            'path': '/v1alpha1/workspaces',
            'name_attrs': ['name'],
            'join_path': '/v1alpha1/workspaces/{0}/policies'
        }
    },
    'policy-recipes': {
        'headers': ['fullName.typeName', 'fullName.name'],
        'api': {
            'path': '/v1alpha1/policy/types/*/recipes',
            'transform': 'recipes[]'
        }
    },
    'cluster-policies': {
        'headers': ['fullName.clusterName', 'spec.type', 'spec.recipe'],
        'api_join': {
            'path': '/v1alpha1/clusters',
            'name_attrs': ['name', 'provisionerName', 'managementClusterName'],
            'join_path': (
                '/v1alpha1/clusters/{0}/policies?'
                + '&searchScope.managementClusterName={1}'
                + '&searchScope.provisionerName={2}'
            )
        }
    },
    'organization-policies': {
        'headers': ['fullName.name', 'spec.type', 'spec.recipe'],
        'api': {
            'path': '/v1alpha1/organization/policies',
            'transform': 'policies[]'
        }
    }

}


def error(msg, label='ERROR'):
    print(color.red('%s: %s' % (label, msg)))


def fatal(msg):
    error(msg, 'FATAL')
    sys.exit(1)


def debug(msg):
    if os.environ.get('TMC_DEBUG') == 'TRUE':
        print(color.green('DEBUG: %s' % msg))


def now_secs():
    return int(round(time.time()))


def delta_secs(start_secs):
    return now_secs() - start_secs


def get_temp_basedir(base_dir=None):
    default_base_dir = '/tmp'
    if sys.platform == 'win32':
        default_base_dir = os.path.join('C:', 'temp')
    if base_dir is None:
        base_dir = os.environ.get('TEMP', default_base_dir)
    return base_dir


def get_cache_file(name):
    return os.path.join(
        get_temp_basedir(),
        'tmc-cache_%s.json' % (name)
    )


def get_cache(name, raw=False):
    cache_file = get_cache_file(name)
    # print('cache_file: %s' % cache_file)
    if os.path.isfile(cache_file):
        d = read_file(cache_file)
        if raw is True:
            return d
        if now_secs() < d['expires']:
            return d['data']
    return None


def write_cache(name, data, expire_secs=None):
    write_file(get_cache_file(name), {
        'expires': now_secs() + (expire_secs or 60),
        'data': data
    }, print_msg=False)


def read_file(file, print_msg=False):
    data = json.loads(open(file, 'r').read())
    if print_msg is True:
        print('read %s' % file)
    return data


def write_file(file, data, print_msg=False):
    with open(file, 'w') as fh:
        fh.write(json.dumps(data, indent=2))
    if print_msg is True:
        print('written %s' % file)


def api(path, method='GET', **kwargs):
    kwargs = dict(**kwargs)
    transform = kwargs.pop('transform', None)
    cache = kwargs.pop('cache', None)
    expire_mins = kwargs.pop('expire_mins', None)
    allowed_codes = kwargs.pop('allowed_codes', [200])
    limit = kwargs.pop('limit', None)
    data = None
    no_cache = os.environ.get('TMC_NO_CACHE') == 'TRUE'
    if cache is not None and no_cache is False:
        data = get_cache(cache)
        if data is not None:
            debug('retrieved %s data from cache' % cache)
            return data

    paginate = kwargs.pop('paginate', None)
    pagination = {
        'pagination.size': 100,
        'includeTotalCount': True
    }
    if limit is not None:
        if limit < pagination['pagination.size']:
            pagination['pagination.size'] = limit

    # get access_token
    access_token = None
    if no_cache is False:
        access_token = get_cache('token')
    if access_token is None:
        r = requests.post(
            'https://console.cloud.vmware.com/csp/gateway/am'
            + '/api/auth/api-tokens/authorize',
            data={'refresh_token': os.environ['TMC_TOKEN']}
        )
        if r.status_code != 200:
            fatal('unable to get access_token HTTP %s: %s' % (
                r.status_code, r.content
            ))
        access_token = r.json()['access_token']
        if no_cache is False:
            write_cache('token', access_token, r.json()['expires_in'])

    if 'headers' not in kwargs:
        kwargs['headers'] = {
            'Authorization': 'Bearer %s' % access_token,
            'Accept': 'application/json'
        }
    url = 'https://%s.tmc.cloud.vmware.com%s' % (
        os.environ['TMC_DOMAIN'], path
    )
    data = []
    while True:
        if paginate is not None:
            if 'params' not in kwargs:
                kwargs['params'] = {}
            kwargs['params'].update(pagination)
        r = requests.Session().request(
            method.lower(), url, **kwargs
        )
        debug('HTTP kwargs: %s' % json.dumps(kwargs, indent=2))
        debug('HTTP %s %s [%s]' % (method.upper(), url, r.status_code))
        if r.status_code not in allowed_codes:
            errmsg = None
            try:
                errmsg = r.json()['error']
            except Exception:
                errmsg = r.content
            fatal('HTTP %s %s [%s] %s' % (
                method, url, r.status_code, errmsg
            ))
        _data = r.json()
        if paginate is not None:
            if paginate not in _data or len(_data[paginate]) == 0:
                break
            data.extend(_data[paginate])
            if str(len(data)) == str(_data.get('totalCount')):
                break
            if limit is not None and len(data) >= limit:
                data = data[0:limit]
                break
            pagination['pagination.offset'] = len(data)
            continue
        else:
            data = _data
        break
    if transform is not None:
        data = jmespath.search(transform, data)
    if cache is not None and no_cache is False:
        write_cache(cache, data, expire_mins=expire_mins)
        debug('written %s data to cache' % cache)
    return data


def api_join(path, name_attrs, join_path, cache=False):
    entity = path.split('?')[0].split('/')[-1]
    data = []

    def _join(d):
        join_entity = join_path.split('?')[0].split('/')[-1]
        data.extend(api(
            join_path.format(*d),
            transform=join_entity + ' || `[]`',
            allowed_codes=[200, 404],
            cache='%s-%s-%s' % (entity, join_entity, d[0]) if cache else None
        ))
    list(EX.map(lambda _: _join(_), api(
        path,
        transform='%s[].fullName.[%s]' % (entity, ', '.join(name_attrs)),
        cache=entity if cache else None
    )))
    return data


def print_table(headers, data, counter=True, sort_key=None, dumpfile=None):
    maxwidth = 40 if len(headers) > 1 else 80
    colwidths = {h: len(h) for h in headers}
    _data = []
    if len(data) == 0:
        print(color.red(' - no data - '))
        return
    if sort_key is not None:
        data = sorted(data, key=lambda k: k[sort_key])
    rc = 0
    if counter is True:
        colwidths[' '] = len(str(len(data)))
        headers.insert(0, ' ')
    for r in data:
        rlines = {}
        linec = 0
        rc += 1
        if counter is True:
            r[' '] = str(rc)
        for h in headers:
            v = jmespath.search(h + ' || ``', r) if '.' in h else r.get(h, '')
            _lines = textwrap.wrap(str(v), width=maxwidth)
            if len(_lines) > linec:
                linec = len(_lines)
            rlines[h] = _lines
            if len(_lines) > 1:
                colwidths[h] = maxwidth
            elif len(_lines) == 1 and len(_lines[0]) > colwidths[h]:
                colwidths[h] = len(_lines[0])
        for lc in range(linec):
            _data.append({
                h: rlines[h][lc] if lc < len(rlines[h]) else ''
                for h in headers
            })

    def _print_line(d, _color=None, sep='|', hcolor={}):
        _line = (' ' + sep + ' ').join(
            str(
                hcolor[h](d[h]) if h in hcolor else
                _color(d[h]) if _color else d[h]
            ).ljust(
                colwidths[h] + (
                    len(hcolor[h]('')) if h in hcolor else
                    len(_color('')) if _color else 0
                )
            )
            for h in headers
        )
        print(_line)

    _print_line(
        {h: h for h in headers}, color.bold, color.blue('|')
    )
    _print_line(
        {h: '-' * colwidths[h] for h in headers},
        color.blue, color.blue('+')
    )
    for r in _data:
        _print_line(r, sep=color.blue('|'), hcolor={
            ' ': color.bold
        })
    if dumpfile is not None:
        dumppath = os.path.join(get_temp_basedir(), dumpfile)
        with open(dumppath, 'w') as fh:
            fh.write(json.dumps(data, indent=2))
        print('written %s' % dumppath)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Tanzu Mission Control API Explorer'
    )
    parser.add_argument(
        'url', help="api path or pdq (use 'pdqs' for list)"
    )
    parser.add_argument(
        '-H', '--headers', help='attribute names in response to use in table'
    )
    parser.add_argument(
        '-l', '--limit', type=int, help='limit results'
    )
    parser.add_argument(
        '-p', '--paginate', help='name of entity to paginate'
    )
    parser.add_argument(
        '-t', '--transform', help='transform response using jmespath'
    )
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--no-cache', action='store_true')
    args = parser.parse_args()

    missing = [
        ev for ev in ['TMC_TOKEN', 'TMC_DOMAIN'] if ev not in os.environ
    ]
    if len(missing) > 0:
        fatal('environment variable(s) required: %s' % ', '.join(missing))

    transform = args.transform
    headers = {}
    if args.debug is True:
        os.environ['TMC_DEBUG'] = 'TRUE'

    if args.no_cache is True:
        os.environ['TMC_NO_CACHE'] = 'TRUE'

    if args.url == 'pdqs':
        print_table(['name'], [{'name': _} for _ in sorted(PDQ_CONFIG.keys())])

    elif args.url in PDQ_CONFIG:
        pdq = PDQ_CONFIG[args.url]
        print_table(
            pdq['headers'],
            api_join(**pdq['api_join'])
            if 'api_join' in pdq else api(**pdq['api']),
            dumpfile=args.url + '.json'
        )

    else:
        if args.headers is not None:
            if args.paginate is None:
                args.paginate = args.url.split('/')[-1]
            for path in args.headers.split(','):
                name = path
                if '.' in path:
                    name = path.split('.')[-1]
                headers[name] = '%s: %s' % (name, path)
            transform = '[].{%s}' % ','.join(headers.values())
        data = api(
            args.url, paginate=args.paginate,
            transform=transform,
            limit=args.limit
        )
        if args.headers is not None:
            print_table(list(headers.keys()), data)
        else:
            print(json.dumps(data, indent=2))
