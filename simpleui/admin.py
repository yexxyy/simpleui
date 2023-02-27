import json
import numpy as np
import traceback
from django.contrib import admin, admin, messages
from django.contrib.admin import helpers
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q
from django.http import JsonResponse, JsonResponse, HttpResponseNotAllowed, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.urls import path
from django.utils.log import log_response
from django.utils.translation import gettext as _
from djongo.models import ObjectIdField
from functools import update_wrapper, wraps


class MyAdmin(admin.ModelAdmin):

    def response_action(self, request, queryset):
        """
        Handle an admin action. This is called if a request is POSTed to the
        changelist; it returns an HttpResponse if the action was handled, and
        None otherwise.
        """

        # There can be multiple action forms on the page (at the top
        # and bottom of the change list, for example). Get the action
        # whose button was pushed.
        try:
            action_index = int(request.POST.get("index", 0))
        except ValueError:
            action_index = 0

        # Construct the action form.
        data = request.POST.copy()
        data.pop(helpers.ACTION_CHECKBOX_NAME, None)
        data.pop("index", None)

        # Use the action whose button was pushed
        try:
            data.update({"action": data.getlist("action")[action_index]})
        except IndexError:
            # If we didn't get an action from the chosen form that's invalid
            # POST data, so by deleting action it'll fail the validation check
            # below. So no need to do anything here
            pass

        action_form = self.action_form(data, auto_id=None)
        action_form.fields["action"].choices = self.get_action_choices(request)

        # If the form's valid we can handle the action.
        if action_form.is_valid():
            action = action_form.cleaned_data["action"]
            select_across = action_form.cleaned_data["select_across"]
            func = self.get_actions(request)[action][0]

            # Get the list of selected PKs. If nothing's selected, we can't
            # perform an action on it, so bail. Except we want to perform
            # the action explicitly on all objects.
            selected = request.POST.getlist(helpers.ACTION_CHECKBOX_NAME)

            # 修复数据库引擎djongo无法删除选中对象问题
            try:
                from bson import ObjectId
                selected = [ObjectId(item) for item in selected]
            except Exception as e:
                pass

            if not selected and not select_across:
                # Reminder that something needs to be selected or nothing will happen
                msg = _(
                    "Items must be selected in order to perform "
                    "actions on them. No items have been changed."
                )
                self.message_user(request, msg, messages.WARNING)
                return None

            if not select_across:
                # Perform the action only on the selected objects
                queryset = queryset.filter(pk__in=selected)

            response = func(self, request, queryset)

            # Actions may return an HttpResponse-like object, which will be
            # used as the response from the POST. If not, we'll be a good
            # little HTTP citizen and redirect back to the changelist page.
            if isinstance(response, HttpResponseBase):
                return response
            else:
                return HttpResponseRedirect(request.get_full_path())
        else:
            msg = _("No action selected.")
            self.message_user(request, msg, messages.WARNING)
            return None


class AjaxAdmin(MyAdmin):
    """
    This class is used to add ajax functionality to the admin interface.
    """
    pk_type = None

    def callback(self, request):
        """
        This method is used to handle ajax requests.
        """
        post = request.POST
        action = post.get("_action")
        selected = post.get("_selected")
        select_across = post.get("select_across")
        obj_id = post.get("obj_id")

        # call admin
        if hasattr(self, action):
            if obj_id:
                try:
                    if self.pk_type:
                        obj_id = self.pk_type(obj_id)
                    obj = self.model.objects.get(pk=obj_id)
                except Exception:
                    return JsonResponse({'msg': '对象不存在', 'status': 'error'})
                dispaly_list_func = getattr(self, action)
                try:
                    return dispaly_list_func(request, obj)
                except Exception as e:
                    return JsonResponse({'msg': str(e), 'status': 'error'})

            func, action, description = self.get_action(action)
            # 这里的queryset 会有数据过滤，只包含选中的数据
            queryset = self.get_changelist_instance(request).get_queryset(request)

            # 没有选择全部的时候才过滤数据
            if select_across == "0":
                if selected and selected.split(","):
                    queryset = queryset.filter(pk__in=selected.split(","))
            else:
                # 过滤搜索条件，自simpleui-2022.3.13版本开始，支持搜索条件过滤，simplepro需要3.4.2及以上版本
                # 只有选择全部的时候才过滤数据
                # 字段为_search和_filter 是为了防止命名冲突

                # search
                if "_search" in post:
                    search_fields = self.get_search_fields(request)

                    if search_fields:
                        search_value = post.get("_search")
                        if search_value:
                            q = Q()
                            for s in search_fields:
                                q = q | Q(**{s + "__icontains": search_value})
                            try:
                                queryset = queryset.filter(q)
                            except Exception as e:
                                traceback.print_exc()
                                raise e

                # filter条件过滤
                if "_filter" in post:
                    _filter = post.get("_filter")
                    if _filter:
                        filter_value = json.loads(_filter)
                        queryset = queryset.filter(**filter_value)

            try:
                return func(self, request, queryset)
            except Exception as e:
                return JsonResponse({'msg': str(e), 'status': 'error'})

    def field_button_callback(self, request, pk):
        """
        This method is used to handle ajax requests.
        """
        post = request.POST
        button = post.get("field_button")
        if button and hasattr(self, button):
            func = getattr(self, button)
            try:
                obj = self.model.objects.get(pk=pk)
            except Exception:
                return JsonResponse({'msg': '对象不存在', 'status': 'error'})
            try:
                return func(request, obj)
            except Exception as e:
                return JsonResponse({'msg': str(e), 'status': 'error'})

    def get_layer(self, request):
        """
        This method is used to get the layer of the admin interface.
        """
        _action = request.GET.get("_action")
        if hasattr(self, _action):
            func, action, description = self.get_action(_action)
            if hasattr(func, "layer"):
                result = func.layer(self, request)
                return JsonResponse(data=result, safe=False)
        else:
            raise Exception(f'action "{_action}" not found')

    def get_urls(self):
        """
        This method is used to add ajax functionality to the admin interface.
        """

        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            wrapper.model_admin = self
            return update_wrapper(wrapper, view)

        info = self.model._meta.app_label, self.model._meta.model_name

        return [
                   path("ajax", self.callback, name="%s_%s_ajax" % info),
                   path("layer", self.get_layer, name="%s_%s_layer" % info),
                   path("<path:pk>/ajax/", wrap(self.field_button_callback), name="%s_%s_change_ajax" % info),
               ] + super().get_urls()
