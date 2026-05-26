from django.shortcuts import (render,redirect,get_object_or_404)
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse
from apps.pointsBalanceSystem.models import (PointExchangeActivity,UserPoint)
from apps.pointsBalanceSystem.forms import (ExchangeFRPForm)
from apps.pointsBalanceSystem.services import (PointsExchangeService)
from apps.login.decorators import (login_required_view)
from apps.login.models import (UserInfo)

@login_required_view
def exchange_list_view(request):
    try:
        user = UserInfo.objects.get(uid=request.session['info']['uid'])
    except UserInfo.DoesNotExist:
        messages.error(request,'用户不存在，请重新登录')
        return redirect('login')

    activities = (PointExchangeActivity.objects.filter(enable=True).order_by('-created_at'))
    points_balance = 0
    try:
        user_point = UserPoint.objects.get(user=user)
        if user_point.enable:
            points_balance = (user_point.points_balance)
    except UserPoint.DoesNotExist:
        pass

    context = {
        'activities': activities,
        'points_balance': points_balance
    }

    return render(request,'pointsBalanceSystem/exchange_list.html',context)


@login_required_view
def exchange_detail_view(request):
    try:
        user = UserInfo.objects.get(uid=request.session['info']['uid'])
    except UserInfo.DoesNotExist:

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': '用户不存在，请重新登录'
            })

        messages.error(
            request,
            '用户不存在，请重新登录'
        )

        return redirect('login')

    aid = request.GET.get('aid')
    if not aid:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': '缺少活动ID'
            })
        messages.error(
            request,
            '缺少活动ID'
        )
        return redirect(
            'points:exchange_list'
        )

    activity = get_object_or_404(PointExchangeActivity,pk=aid,enable=True)

    points_balance = 0
    try:
        user_point = UserPoint.objects.get(user=user)
        if user_point.enable:
            points_balance = (
                user_point.points_balance
            )
    except UserPoint.DoesNotExist:
        pass

    if request.method == 'POST':
        form = ExchangeFRPForm(
            request.POST,
            user=user,
            activity=activity
        )

        is_ajax = (
            request.headers.get('x-requested-with') == 'XMLHttpRequest')

        if form.is_valid():
            quantity = form.cleaned_data['quantity']
            service = PointsExchangeService(
                user=user,
                activity=activity,
                quantity=quantity
            )
            try:
                record = service.execute()
                user_point = UserPoint.objects.get(
                    user=user
                )
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'message': (
                            f'兑换成功！'
                            f'获得 {record.reward_value} 秒FRP时长，'
                            f'消耗 {record.points_deducted} 积分。'
                        ),
                        'points_balance': (
                            user_point.points_balance
                        )
                    })

                messages.success(
                    request,
                    f'兑换成功！'
                    f'获得 {record.reward_value} 秒FRP时长，'
                    f'消耗 {record.points_deducted} 积分。'
                )
                return redirect(f"{reverse('points:exchange_detail')}?aid={aid}")
            except (
                ValueError,
                RuntimeError
            ) as e:

                if is_ajax:

                    return JsonResponse({
                        'success': False,
                        'message': str(e)
                    })

                messages.error(
                    request,
                    str(e)
                )
        else:

            if is_ajax:
                error_list = []
                for field, errors in form.errors.items():
                    for error in errors:
                        error_list.append(error)
                return JsonResponse({
                    'success': False,
                    'message': '；'.join(error_list)
                })
    else:
        form = ExchangeFRPForm(
            user=user,
            activity=activity
        )
    context = {
        'form': form,
        'activity': activity,
        'aid': aid,
        'points_balance': points_balance
    }

    return render(
        request,
        'pointsBalanceSystem/exchange_detail.html',
        context
    )