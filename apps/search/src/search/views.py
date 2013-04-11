#!/usr/bin/env python
# Licensed to Cloudera, Inc. under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  Cloudera, Inc. licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

try:
  import json
except ImportError:
  import simplejson as json

import logging

from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.utils.translation import ugettext as _
from django.shortcuts import redirect

from desktop.lib.django_util import render

from search.api import SolrApi
from search.conf import SOLR_URL
from search.decorators import allow_admin_only
from search.forms import QueryForm, CoreForm, HighlightingForm
from search.models import Core


LOG = logging.getLogger(__name__)


def index(request):
  cores = SolrApi(SOLR_URL.get()).cores()
  hue_cores = Core.objects.all()

  for core in cores['status']:
    Core.objects.get_or_create(name=core)

  search_form = QueryForm(request.GET)
  response = {}
  error = {}
  solr_query = {}

  if search_form.is_valid():
    core = search_form.cleaned_data['cores']
    solr_query['core'] = core
    solr_query['q'] = search_form.cleaned_data['query']
    solr_query['fq'] = search_form.cleaned_data['fq']
    solr_query['sort'] = search_form.cleaned_data['sort'] or 'score desc'
    solr_query['rows'] = search_form.cleaned_data['rows'] or 15
    solr_query['start'] = search_form.cleaned_data['start'] or 0
    solr_query['facets'] = search_form.cleaned_data['facets'] or 1

    hue_core = Core.objects.get_or_create(name=core)

    try:
      response = SolrApi(SOLR_URL.get()).query(solr_query, hue_core)
    except Exception, e:
      error['message'] = unicode(str(e), "utf8")

  return render('index.mako', request, {
    'search_form': search_form,
    'response': augment_solr_response(response, hue_core.facets.get_data()),
    'error': error,
    'solr_query': solr_query,
    'hue_core': hue_core,
    'hue_cores': hue_cores,
    'current_cores': request.GET and request.GET['cores'] or '',
    'json': json,
  })

def get_facet_field_label(field, type, facets):
  label = field
  if type == 'field':
    for fld in facets['fields']:
      if fld['field'] == field:
        label = fld['label']
  elif type == 'range':
    for fld in facets['ranges']:
      if fld['field'] == field:
        label = fld['label']
  elif type == 'date':
    for fld in facets['dates']:
      if fld['field'] == field:
        label = fld['label']
  return label

def get_facet_field_uuid(field, type, facets):
  uuid = ''
  if type == 'field':
    for fld in facets['fields']:
      if fld['field'] == field:
        uuid = fld['uuid']
  elif type == 'range':
    for fld in facets['ranges']:
      if fld['field'] == field:
        uuid = fld['uuid']
  elif type == 'date':
    for fld in facets['dates']:
      if fld['field'] == field:
        uuid = fld['uuid']
  return uuid


def augment_solr_response(response, facets):
  augmented = response
  augmented['normalized_facets'] = []

  normalized_facets = {}
  if response and response.get('facet_counts'):
    if response['facet_counts']['facet_fields']:
      for cat in response['facet_counts']['facet_fields']:
        facet = {
          'field': cat,
          'type': 'field',
          'label': get_facet_field_label(cat, 'field', facets),
          'counts': response['facet_counts']['facet_fields'][cat],
        }
        normalized_facets[get_facet_field_uuid(cat, 'field', facets)] = facet

    if response['facet_counts']['facet_ranges']:
      for cat in response['facet_counts']['facet_ranges']:
        facet = {
          'field': cat,
          'type': 'range',
          'label': get_facet_field_label(cat, 'range', facets),
          'counts': response['facet_counts']['facet_ranges'][cat]['counts'],
          'start': response['facet_counts']['facet_ranges'][cat]['start'],
          'end': response['facet_counts']['facet_ranges'][cat]['end'],
          'gap': response['facet_counts']['facet_ranges'][cat]['gap'],
        }
        normalized_facets[get_facet_field_uuid(cat, 'range', facets)] = facet

    if response['facet_counts']['facet_dates']:
      for cat in response['facet_counts']['facet_dates']:
        facet = {
          'field': cat,
          'type': 'date',
          'label': get_facet_field_label(cat, 'date', facets),
          'start': response['facet_counts']['facet_dates'][cat]['start'],
          'end': response['facet_counts']['facet_dates'][cat]['end'],
          'gap': response['facet_counts']['facet_dates'][cat]['gap'],
        }
        counts = []
        for date, count in response['facet_counts']['facet_dates'][cat].iteritems():
          if date not in ('start', 'end', 'gap'):
            counts.append(date)
            counts.append(count)
        facet['counts'] = counts
        normalized_facets[get_facet_field_uuid(cat, 'date', facets)] = facet

  for ordered_uuid in facets['order']:
    try:
      augmented['normalized_facets'].append(normalized_facets[ordered_uuid])
    except:
      pass

  return augmented

@allow_admin_only
def admin(request):
  # To cross check both
  cores = SolrApi(SOLR_URL.get()).cores()
  hue_cores = Core.objects.all()

  return render('admin.mako', request, {
    'cores': cores,
    'hue_cores': hue_cores,
  })


@allow_admin_only
def admin_core_properties(request, core):
  solr_core = SolrApi(SOLR_URL.get()).core(core)
  hue_core = Core.objects.get(name=core)
  hue_cores = Core.objects.all()

  if request.method == 'POST':
    core_form = CoreForm(request.POST, instance=hue_core)
    if core_form.is_valid():
      hue_core = core_form.save()
      return redirect(reverse('search:admin_core_properties', kwargs={'core': hue_core.name}))
    else:
      request.error(_('Errors on the form: %s') % core_form.errors)
  else:
    core_form = CoreForm(instance=hue_core)

  return render('admin_core_properties.mako', request, {
    'solr_core': solr_core,
    'hue_core': hue_core,
    'hue_cores': hue_cores,
    'core_form': core_form,
  })


@allow_admin_only
def admin_core_template(request, core):
  solr_core = SolrApi(SOLR_URL.get()).core(core)
  hue_core = Core.objects.get(name=core)
  hue_cores = Core.objects.all()

  if request.method == 'POST':
    hue_core.result.update_from_post(request.POST)
    hue_core.result.save()
    return HttpResponse(json.dumps({}), mimetype="application/json")

  solr_query = {}
  solr_query['core'] = core
  solr_query['q'] = ''
  solr_query['fq'] = ''
  solr_query['rows'] = 5
  solr_query['start'] = 0
  solr_query['facets'] = 0

  response = SolrApi(SOLR_URL.get()).query(solr_query, hue_core)

  return render('admin_core_template.mako', request, {
    'solr_core': solr_core,
    'hue_core': hue_core,
    'hue_cores': hue_cores,
    'sample_data': json.dumps(response["response"]["docs"]),
  })


@allow_admin_only
def admin_core_facets(request, core):
  solr_core = SolrApi(SOLR_URL.get()).core(core)
  hue_core = Core.objects.get(name=core)
  hue_cores = Core.objects.all()

  if request.method == 'POST':
    print request.POST
    hue_core.facets.update_from_post(request.POST)
    hue_core.facets.save()
    return HttpResponse(json.dumps({}), mimetype="application/json")

  return render('admin_core_facets.mako', request, {
    'solr_core': solr_core,
    'hue_core': hue_core,
    'hue_cores': hue_cores,
  })


@allow_admin_only
def admin_core_sorting(request, core):
  solr_core = SolrApi(SOLR_URL.get()).core(core)
  hue_core = Core.objects.get(name=core)
  hue_cores = Core.objects.all()

  if request.method == 'POST':
    hue_core.sorting.update_from_post(request.POST)
    hue_core.sorting.save()
    return HttpResponse(json.dumps({}), mimetype="application/json")

  return render('admin_core_sorting.mako', request, {
    'solr_core': solr_core,
    'hue_core': hue_core,
    'hue_cores': hue_cores,
  })


@allow_admin_only
def admin_core_highlighting(request, core):
  solr_core = SolrApi(SOLR_URL.get()).core(core)
  hue_core = Core.objects.get(name=core)
  hue_cores = Core.objects.all()

  if request.method == 'POST':
    hue_core.result.update_from_post(request.POST)
    hue_core.result.save()
    return HttpResponse(json.dumps({}), mimetype="application/json")

  return render('admin_core_highlighting.mako', request, {
    'solr_core': solr_core,
    'hue_core': hue_core,
    'hue_cores': hue_cores,
  })


# Ajax below

@allow_admin_only
def admin_core_solr_properties(request, core):
  solr_core = SolrApi(SOLR_URL.get()).core(core)
  hue_core = Core.objects.get(name=core)
  hue_cores = Core.objects.all()

  content = render('admin_core_properties_solr_properties.mako', request, {
    'solr_core': solr_core,
    'hue_core': hue_core,
    'hue_cores': hue_cores,
  }, force_template=True).content

  return HttpResponse(json.dumps({'content': content}), mimetype="application/json")


@allow_admin_only
def admin_core_schema(request, core):
  solr_schema = SolrApi(SOLR_URL.get()).schema(core)
  hue_core = Core.objects.get(name=core)
  hue_cores = Core.objects.all()

  content = render('admin_core_properties_solr_schema', request, {
    'solr_schema': solr_schema,
    'hue_core': hue_core,
    'hue_cores': hue_cores,
  }, force_template=True).content

  return HttpResponse(json.dumps({'content': content}), mimetype="application/json")


# TODO security
def query_suggest(request, core, query=""):
  hue_core = Core.objects.get(name=core)
  result = {'status': -1, 'message': 'Error'}

  solr_query = {}
  solr_query['core'] = core
  solr_query['q'] = query

  try:
    response = SolrApi(SOLR_URL.get()).suggest(solr_query, hue_core)
    result['message'] = response
    result['status'] = 0
  except Exception, e:
    error['message'] = unicode(str(e), "utf8")

  return HttpResponse(json.dumps(result), mimetype="application/json")