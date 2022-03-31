# tmc
Tanzu Mission Control API Explorer

## Usage

Both `TMC_DOMAIN` and `TMC_TOKEN` environment variables must be set to use this tool

```
usage: tmc.py [-h] [-l LIMIT] [-p PAGINATE] [-H HEADERS] [--debug] [--no-cache] url

Tanzu Mission Control API Explorer

positional arguments:
  url                   api path or pdq (use 'pdqs' for list)

optional arguments:
  -h, --help            show this help message and exit
  -l LIMIT, --limit LIMIT
                        limit results
  -p PAGINATE, --paginate PAGINATE
                        name of entity to paginate
  -H HEADERS, --headers HEADERS
                        attribute names in response to use in table
  --debug
  --no-cache

```

## API Documentation

* https://developer.vmware.com/apis/1079/tanzu-mission-control

## Usage Examples

### List PDQs (Pre Defined Queries)

```
$ python tmc.py pdqs

  | name
- + ---------------------
1 | cluster-policies
2 | organization-policies
3 | policy-recipes
4 | workspace-policies
```

NOTE: Not all the APIs work as expected currently (eg [PolicyResourceService](https://developer.vmware.com/apis/1079/tanzu-mission-control#/PolicyResourceService) and `*` globbing) so tmc.py needs to perform various API joins achieved with some of the PDQs

### Policy Recipies

```
$ python tmc.py policy-recipies

   | fullName.typeName      | fullName.name
-- + ---------------------- + ----------------------------------------
1  | image-policy           | custom
2  | image-policy           | block-latest-tag
3  | image-policy           | require-digest
4  | image-policy           | allowed-name-tag
5  | network-policy         | allow-all-to-pods
6  | network-policy         | custom-egress
7  | network-policy         | custom-ingress
8  | network-policy         | deny-all-to-pods
9  | network-policy         | allow-all
10 | network-policy         | deny-all
11 | security-policy        | strict
12 | security-policy        | baseline
13 | security-policy        | custom
14 | namespace-quota-policy | large
15 | namespace-quota-policy | custom
16 | namespace-quota-policy | small
17 | namespace-quota-policy | medium
18 | custom-policy          | tmc-block-rolebinding-subjects
```

### List Workspaces

```
$ python tmc.py /v1alpha1/workspaces -H fullName.name

   | name
-- + ------------------------
1  | some-workspace
2  | default
3  | demo-workspace
```

### Get Cluster

```
$ python tmc.py '/v1alpha1/clusters/foobar?full_name.managementClusterName=attached&full_nameprovisionerName=attached' --transform 'cluster.status.[infrastructureProvider, health]'

[
  "AWS_EC2",
  "DISCONNECTED"
]
```
