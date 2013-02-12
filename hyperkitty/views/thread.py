# -*- coding: utf-8 -*-
# Copyright (C) 1998-2012 by the Free Software Foundation, Inc.
#
# This file is part of HyperKitty.
#
# HyperKitty is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# HyperKitty is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# HyperKitty.  If not, see <http://www.gnu.org/licenses/>.
#
# Author: Aamir Khan <syst3m.w0rm@gmail.com>
# Author: Aurelien Bompard <abompard@fedoraproject.org>
#

import datetime

import django.utils.simplejson as simplejson

from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.template import RequestContext, loader
from django.conf import settings
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger, InvalidPage
from django.core.urlresolvers import reverse
from django.core.exceptions import SuspiciousOperation
from django.utils.datastructures import SortedDict
from django.contrib.auth.decorators import (login_required,
                                            permission_required,
                                            user_passes_test)

from hyperkitty.models import Tag, Favorite
#from hyperkitty.lib.mockup import *
from forms import *
from hyperkitty.lib import get_months, get_store, stripped_subject, get_votes


def thread_index(request, mlist_fqdn, threadid, month=None, year=None):
    ''' Displays all the email for a given thread identifier '''
    search_form = SearchForm(auto_id=False)
    t = loader.get_template('thread.html')
    store = get_store(request)
    thread = store.get_thread(mlist_fqdn, threadid)
    if not thread:
        raise Http404
    prev_thread, next_thread = store.get_thread_neighbors(mlist_fqdn, threadid)

    if "sort" in request.GET and request.GET["sort"] == "date":
        sort_mode = "date"
        emails = thread.emails
    else:
        sort_mode = "thread"
        emails = thread.emails_by_reply

    participants = {}
    for email in emails:
        # Extract all the votes for this message
        email.likes, email.dislikes = get_votes(email.message_id_hash)
        email.likestatus = "neutral"
        if email.likes - email.dislikes >= 10:
            email.likestatus = "likealot"
        elif email.likes - email.dislikes > 0:
            email.likestatus = "like"
        #elif email.likes - email.dislikes < 0:
        #    email.likestatus = "dislike"


        # Statistics on how many participants and messages this month
        participants[email.sender_name] = email.sender_email

        if sort_mode == "thread":
            email.level = email.thread_depth - 1 # replies start ragged left
            if email.level > 5:
                email.level = 5

    from_url = reverse("thread", kwargs={"mlist_fqdn":mlist_fqdn,
                                         "threadid":threadid})
    # Tags
    tag_form = AddTagForm(initial={'from_url' : from_url})
    try:
        tags = Tag.objects.filter(threadid=threadid, list_address=mlist_fqdn)
    except Tag.DoesNotExist:
        tags = {}

    # Favorites
    fav_action = "add"
    if request.user.is_authenticated():
        try:
            Favorite.objects.get(list_address=mlist_fqdn, threadid=threadid,
                                 user=request.user)
        except Favorite.DoesNotExist:
            pass
        else:
            fav_action = "rm"

    # Extract relative dates
    today = datetime.date.today()
    days_old = today - thread.starting_email.date.date()
    days_inactive = today - thread.last_email.date.date()

    mlist = store.get_list(mlist_fqdn)
    subject = stripped_subject(mlist, thread.starting_email.subject)

    c = RequestContext(request, {
        'mlist' : mlist,
        'threadid' : threadid,
        'subject': subject,
        'tags' : tags,
        'search_form': search_form,
        'addtag_form': tag_form,
        'month': thread.date_active,
        'participants': participants,
        'first_mail': thread.starting_email,
        'replies': list(emails)[1:],
        'neighbors': (prev_thread, next_thread),
        'months_list': get_months(store, mlist.name),
        'days_inactive': days_inactive.days,
        'days_old': days_old.days,
        'use_mockups': settings.USE_MOCKUPS,
        'sort_mode': sort_mode,
        'fav_action': fav_action,
        'reply_form': ReplyForm(),
    })
    return HttpResponse(t.render(c))


def add_tag(request, mlist_fqdn, threadid):
    """ Add a tag to a given thread. """
    if not request.user.is_authenticated():
        return HttpResponse('You must be logged in to add a tag',
                            content_type="text/plain", status=403)

    if request.method != 'POST':
        raise SuspiciousOperation

    form = AddTagForm(request.POST)
    if not form.is_valid():
        return HttpResponse("Error adding tag: invalid data",
                            content_type="text/plain", status=500)
    tag = form.data['tag']
    try:
        tag_obj = Tag.objects.get(threadid=threadid,
                                  list_address=mlist_fqdn, tag=tag)
    except Tag.DoesNotExist:
        tag_obj = Tag(list_address=mlist_fqdn, threadid=threadid, tag=tag)
        tag_obj.save()

    # Now refresh the tag list
    tags = Tag.objects.filter(threadid=threadid, list_address=mlist_fqdn)
    t = loader.get_template('threads/tags.html')
    html = t.render(RequestContext(request, {
            "tags": tags,
            "list_address": mlist_fqdn}))

    response = {"tags": [ t.tag for t in tags ], "html": html}
    return HttpResponse(simplejson.dumps(response),
                        mimetype='application/javascript')



def favorite(request, mlist_fqdn, threadid):
    """ Add or remove from favorites"""
    if not request.user.is_authenticated():
        return HttpResponse('You must be logged in to have favorites',
                            content_type="text/plain", status=403)

    if request.method != 'POST':
        raise SuspiciousOperation

    props = dict(list_address=mlist_fqdn, threadid=threadid, user=request.user)
    if request.POST["action"] == "add":
        try:
            fav = Favorite.objects.get(**props)
        except Favorite.DoesNotExist:
            fav = Favorite(**props)
        fav.save()
    elif request.POST["action"] == "rm":
        try:
            fav = Favorite.objects.get(**props)
        except Favorite.DoesNotExist:
            pass
        else:
            fav.delete()
    else:
        raise SuspiciousOperation
    return HttpResponse("success", mimetype='text/plain')

