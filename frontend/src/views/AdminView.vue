<template>
  <SidebarProvider>
    <!-- 桌面端（md+）侧边栏：图标 + 文字严格左对齐，选中项高亮；手机端不展示（导航走底部栏） -->
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton as-child size="lg">
              <RouterLink to="/" class="font-display font-bold">
                <span class="grid size-7 shrink-0 place-items-center rounded-lg bg-linear-to-br from-primary to-(--brand-deep) text-primary-foreground" aria-hidden="true">
                  <Printer class="size-3.5" />
                </span>
                <span class="truncate">PrintHub 后台</span>
              </RouterLink>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem v-for="item in tabs" :key="item.key">
                <SidebarMenuButton :is-active="tab === item.key" class="h-10 font-medium" @click="tab = item.key" :title="item.label">
                  <component :is="item.icon" />
                  <span>{{ item.label }}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton as-child class="h-10 font-medium">
              <RouterLink to="/">
                <House />
                <span>返回前台首页</span>
              </RouterLink>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>

    <SidebarInset class="flex min-h-svh flex-col">
      <!-- 顶栏：admin 路由唯一顶栏（h-14 与侧边栏成比例）——左侧折叠开关 + 标题，右侧主题切换 + 退出 -->
      <header class="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b bg-background/85 px-3 backdrop-blur-md sm:px-5">
        <SidebarTrigger class="hidden md:inline-flex" />
        <Separator orientation="vertical" class="hidden h-5! md:block" />
        <h1 class="truncate text-sm font-medium">{{ currentTabLabel }} · 后台管理</h1>
        <div class="ml-auto flex items-center gap-1.5">
          <ThemeToggle />
          <Button variant="outline" size="sm" class="h-9 rounded-full px-4" @click="auth.logout()">退出</Button>
        </div>
      </header>

      <!-- 通栏紧凑布局：不限窄宽，内容铺满侧边栏以外的可用宽度；底部为手机端 Tab 栏预留安全区 -->
      <div class="w-full flex-1 p-3 pb-[calc(76px+env(safe-area-inset-bottom))] sm:p-4 md:pb-4">
        <Card class="gap-4 py-4 sm:py-5">
          <CardContent class="grid gap-4 px-3 sm:px-5">
            <Alert
              v-if="feedback"
              :class="feedbackType === 'warning'
                ? 'border-warning/30 bg-warning/10 text-warning'
                : 'border-success/30 bg-success/10 text-success'"
            >
              <TriangleAlert v-if="feedbackType === 'warning'" class="size-4" />
              <CircleCheck v-else class="size-4" />
              <AlertDescription :class="feedbackType === 'warning' ? 'text-warning' : 'text-success'">{{ feedback }}</AlertDescription>
            </Alert>

            <!-- ============ 概览 ============ -->
            <template v-if="tab === 'dashboard'">
              <div class="grid gap-1.5">
                <p class="text-[13px] font-bold tracking-widest text-primary">后台首页</p>
                <h2 class="font-display text-2xl font-bold tracking-tight">运营概览</h2>
              </div>
              <div class="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
                <Card v-for="metric in dashboardMetrics" :key="metric.label" class="gap-1 rounded-xl py-3">
                  <CardContent class="grid gap-0.5 px-3.5">
                    <span class="text-[13px] text-muted-foreground">{{ metric.label }}</span>
                    <strong class="font-display text-lg font-bold text-foreground tabular-nums sm:text-xl">{{ metric.value }}</strong>
                  </CardContent>
                </Card>
              </div>
              <DailyStatsCard />
            </template>

            <!-- ============ 订单 ============ -->
            <template v-if="tab === 'orders'">
              <h2 class="font-display text-2xl font-bold tracking-tight">订单管理</h2>

              <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div class="grid gap-1">
                    <p class="text-[13px] font-bold tracking-widest text-primary">打印排队</p>
                    <h3 class="font-display text-lg font-bold">实时排队看板</h3>
                  </div>
                  <Button variant="secondary" class="h-9" :disabled="queueRefreshing" @click="refreshPrintStatus">
                    <RefreshCw />
                    {{ queueRefreshing ? '刷新中…' : '刷新打印状态' }}
                  </Button>
                </div>
                <div class="flex flex-wrap gap-2">
                  <Badge variant="outline" class="h-6 border-primary/25 bg-accent text-accent-foreground">正在打印：{{ printQueue.printing_count || 0 }}</Badge>
                  <Badge variant="outline" class="h-6 border-warning/30 bg-warning/10 text-warning">排队中：{{ printQueue.waiting_count || 0 }}</Badge>
                  <Badge variant="secondary" class="h-6">队列总数：{{ printQueue.total || 0 }}</Badge>
                </div>
                <div v-if="(printQueue.items || []).length === 0" class="rounded-lg border border-dashed bg-card px-4 py-6 text-center text-sm text-muted-foreground">
                  当前没有正在打印或排队的订单
                </div>
                <div v-else class="grid gap-2">
                  <div v-for="item in printQueue.items" :key="item.id" class="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border bg-card px-3.5 py-2.5 text-sm">
                    <span class="font-display font-bold text-primary">#{{ item.position }}</span>
                    <div class="grid min-w-0 flex-1 gap-0.5">
                      <strong class="break-all text-foreground">{{ item.id }}</strong>
                      <span class="text-[13px] text-muted-foreground">{{ item.contact_name || '匿名' }} · {{ item.printer_name || '默认打印机' }} · {{ item.copies || 1 }} 份</span>
                    </div>
                    <Badge :class="item.status === 'printing' ? 'border-transparent bg-accent text-accent-foreground' : 'border-transparent bg-warning/15 text-warning'">
                      {{ item.status === 'printing' ? '正在打印' : '排队中' }}
                    </Badge>
                  </div>
                </div>
              </section>

              <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                <div class="grid gap-1">
                  <p class="text-[13px] font-bold tracking-widest text-primary">文件缓存</p>
                  <h3 class="font-display text-lg font-bold">按时段清理</h3>
                </div>
                <div class="grid gap-3 sm:grid-cols-2">
                  <div class="grid gap-1.5">
                    <Label for="cache-start" class="text-sm font-bold">开始时间</Label>
                    <Input id="cache-start" v-model="cacheCleanup.start_at" type="datetime-local" class="h-10 bg-card" />
                  </div>
                  <div class="grid gap-1.5">
                    <Label for="cache-end" class="text-sm font-bold">结束时间</Label>
                    <Input id="cache-end" v-model="cacheCleanup.end_at" type="datetime-local" class="h-10 bg-card" />
                  </div>
                </div>
                <div class="flex flex-wrap items-center gap-3">
                  <label class="flex cursor-pointer items-center gap-2 text-sm text-foreground">
                    <Checkbox v-model="cacheCleanup.include_order_files" />
                    包含订单关联文件缓存
                  </label>
                  <Button variant="secondary" class="h-9 flex-1 sm:flex-none" @click="previewFileCacheCleanup">
                    <Search />
                    统计可清理缓存
                  </Button>
                  <Button variant="destructive" class="h-9 flex-1 sm:flex-none" @click="cleanupFileCache">
                    <Trash2 />
                    执行清理
                  </Button>
                </div>
                <div v-if="cacheCleanupResult" class="grid gap-2 rounded-lg border bg-card p-3.5 text-sm">
                  <strong class="text-foreground">{{ cacheCleanupResult.dry_run ? '统计结果' : '清理结果' }}</strong>
                  <span class="text-muted-foreground">
                    命中 {{ cacheCleanupResult.matched }} 个文件，已清理 {{ cacheCleanupResult.deleted }} 个，跳过 {{ cacheCleanupResult.skipped }} 个，可释放/已释放 {{ Number(cacheCleanupResult.releasable_mb || 0).toFixed(2) }} MB
                  </span>
                  <div v-for="file in cacheCleanupResult.files.slice(0, 12)" :key="file.id" class="flex flex-wrap items-baseline justify-between gap-x-3 border-t pt-1.5">
                    <span class="break-all text-foreground">{{ file.original_name }}</span>
                    <small class="text-xs text-muted-foreground">{{ file.uploaded_at }} · {{ file.action }} · {{ file.reason }} · {{ Number(file.size_mb || 0).toFixed(2) }} MB</small>
                  </div>
                </div>
              </section>

              <div class="flex flex-wrap items-center justify-between gap-3">
                <div class="grid gap-1">
                  <p class="text-[13px] font-bold tracking-widest text-primary">订单列表</p>
                  <h3 class="font-display text-lg font-bold">最近订单</h3>
                </div>
                <Button variant="destructive" class="h-9" :disabled="unpaidOrdersCount === 0" @click="deleteAllUnpaidOrders">
                  <Trash2 />
                  删除全部未支付<span v-if="unpaidOrdersCount">（{{ unpaidOrdersCount }}）</span>
                </Button>
              </div>

              <div class="grid gap-2">
                <div v-for="order in orders" :key="order.id" class="grid gap-2.5 rounded-xl border bg-card p-3.5 lg:grid-cols-[minmax(0,1fr)_auto]">
                  <div class="grid gap-1.5">
                    <div class="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                      <strong class="break-all text-sm font-bold text-foreground">{{ order.id }}</strong>
                      <strong class="font-display text-base font-bold text-primary tabular-nums">¥{{ Number(order.total_amount).toFixed(2) }}</strong>
                      <span v-if="Number(order.discount_amount || 0) > 0" class="text-xs text-success">优惠 ¥{{ Number(order.discount_amount || 0).toFixed(2) }}</span>
                    </div>
                    <div class="flex flex-wrap gap-x-4 gap-y-0.5 text-[13px] text-muted-foreground">
                      <span>创建 {{ order.created_at || '-' }}</span>
                      <span>打印机 {{ order.printer_name || '默认打印机' }}</span>
                      <span>{{ formatPaymentMethod(order.payment_method) }}</span>
                    </div>
                    <div class="flex flex-wrap gap-2">
                      <Badge :class="statusBadgeClass(paymentStatusClass(order))">支付状态：{{ formatOrderPaymentStatus(order) }}</Badge>
                      <Badge :class="statusBadgeClass(printStatusClass(order.status))">打印状态：{{ formatPrintStatus(order.status) }}</Badge>
                    </div>
                  </div>
                  <div class="flex flex-wrap items-start gap-2 lg:justify-end">
                    <Button variant="secondary" size="sm" class="h-8" @click="loadOrderDetail(order.id)">
                      <Eye />
                      详情
                    </Button>
                    <Button v-if="canCompleteOrder(order)" variant="secondary" size="sm" class="h-8" @click="completeOrder(order.id)">完成</Button>
                    <Button v-if="!canDeleteUnpaid(order)" variant="destructive" size="sm" class="h-8" @click="deleteOrder(order)">
                      <Trash2 />
                      删除订单
                    </Button>
                    <Button v-if="canDeleteUnpaid(order)" variant="destructive" size="sm" class="h-8" @click="deleteUnpaidOrder(order)">
                      <Trash2 />
                      删除未支付
                    </Button>
                  </div>
                </div>
                <div v-if="orders.length === 0" class="rounded-lg border border-dashed bg-muted/40 px-4 py-8 text-center text-sm text-muted-foreground">暂无订单</div>
              </div>
              <!-- 订单详情改为 Dialog 弹窗展示（见模板底部的订单详情弹窗），不再内嵌在列表下方 -->
            </template>

            <!-- ============ 用户 ============ -->
            <template v-if="tab === 'users'">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div class="grid gap-1">
                  <p class="text-[13px] font-bold tracking-widest text-primary">管理员</p>
                  <h2 class="font-display text-2xl font-bold tracking-tight">用户管理</h2>
                </div>
                <Button variant="secondary" class="h-9" @click="resetUserForm">
                  <Plus />
                  新增用户
                </Button>
              </div>

              <form class="grid gap-3 rounded-xl border bg-muted/40 p-4" @submit.prevent="saveUser">
                <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  <div class="grid gap-1.5">
                    <Label for="user-username" class="text-sm font-bold">用户名</Label>
                    <Input id="user-username" v-model="userForm.username" required class="h-10 bg-card" />
                  </div>
                  <div class="grid gap-1.5">
                    <Label for="user-password" class="text-sm font-bold">密码</Label>
                    <Input id="user-password" v-model="userForm.password" type="password" :required="!userForm.id" :placeholder="userForm.id ? '留空则不修改' : '8-64 位'" class="h-10 bg-card" />
                  </div>
                  <div class="grid gap-1.5">
                    <Label for="user-email" class="text-sm font-bold">邮箱</Label>
                    <Input id="user-email" v-model="userForm.email" type="email" class="h-10 bg-card" />
                  </div>
                  <div class="grid gap-1.5">
                    <Label for="user-phone" class="text-sm font-bold">手机号</Label>
                    <Input id="user-phone" v-model="userForm.phone" class="h-10 bg-card" />
                  </div>
                  <div class="grid gap-1.5">
                    <Label for="user-balance" class="text-sm font-bold">{{ userForm.id ? '账户余额' : '初始余额' }}</Label>
                    <Input id="user-balance" v-model.number="userForm.balance" type="number" min="0" step="0.01" class="h-10 bg-card" />
                  </div>
                </div>
                <div class="flex flex-wrap items-center gap-x-5 gap-y-3">
                  <label class="flex cursor-pointer items-center gap-2 text-sm text-foreground">
                    <Checkbox v-model="userForm.is_admin" />
                    管理员
                  </label>
                  <label class="flex cursor-pointer items-center gap-2 text-sm text-foreground">
                    <Checkbox v-model="userForm.is_active" />
                    启用账户
                  </label>
                  <Button type="submit" class="h-9 ml-auto">
                    <Save />
                    {{ userForm.id ? '保存修改' : '创建用户' }}
                  </Button>
                </div>
              </form>

              <div class="grid gap-2">
                <div v-for="user in users" :key="user.id" class="grid gap-2.5 rounded-xl border bg-card p-3.5 xl:grid-cols-[minmax(0,1fr)_auto]">
                  <div class="grid min-w-0 gap-1.5">
                    <div class="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                      <strong class="text-sm font-bold text-foreground">{{ user.username }}</strong>
                      <strong class="font-display text-base font-bold text-primary tabular-nums">¥{{ Number(user.balance || 0).toFixed(2) }}</strong>
                      <Badge :class="user.is_active ? 'border-transparent bg-success/10 text-success' : 'border-transparent bg-warning/15 text-warning'">{{ user.is_active ? '启用' : '已封禁' }}</Badge>
                      <Badge v-if="user.is_admin" variant="outline">{{ '管理员' }}</Badge>
                    </div>
                    <span class="break-all text-[13px] text-muted-foreground">{{ user.email || '未填邮箱' }} · {{ user.phone || '未填手机号' }}</span>
                    <small class="text-xs text-muted-foreground">{{ user.id }}</small>
                    <div class="flex flex-wrap gap-2 pt-1">
                      <label class="grid gap-1 text-xs text-muted-foreground">
                        <span>余额增减</span>
                        <Input v-model.number="balanceDeltas[user.id]" type="number" step="0.01" placeholder="例如 10" class="h-9 w-40 bg-card" />
                      </label>
                      <label class="grid gap-1 text-xs text-muted-foreground">
                        <span>修改余额</span>
                        <Input v-model.number="balanceTargets[user.id]" type="number" min="0" step="0.01" placeholder="例如 20" class="h-9 w-40 bg-card" />
                      </label>
                    </div>
                  </div>
                  <div class="flex flex-wrap content-start items-start gap-2 xl:justify-end">
                    <Button variant="secondary" size="sm" class="h-8" @click="fillUser(user)">
                      <Pencil />
                      编辑
                    </Button>
                    <Button variant="secondary" size="sm" class="h-8" @click="adjustBalance(user.id)">
                      <Plus />
                      加减余额
                    </Button>
                    <Button variant="secondary" size="sm" class="h-8" @click="setBalance(user.id)">
                      <Save />
                      修改余额
                    </Button>
                    <Button variant="secondary" size="sm" class="h-8" @click="toggleUser(user)">
                      <Power />
                      {{ user.is_active ? '封禁' : '解封' }}
                    </Button>
                    <Button variant="destructive" size="sm" class="h-8" :disabled="!!userDeleteBlockReason(user)" :title="userDeleteBlockReason(user) || `删除 ${user.username}`" @click="deleteUser(user)">
                      <Trash2 />
                      删除
                    </Button>
                  </div>
                </div>
                <div v-if="users.length === 0" class="rounded-lg border border-dashed bg-muted/40 px-4 py-8 text-center text-sm text-muted-foreground">暂无用户</div>
              </div>
            </template>

            <!-- ============ 配置 ============ -->
            <template v-if="tab === 'settings'">
              <h2 class="font-display text-2xl font-bold tracking-tight">系统设置</h2>

              <div class="grid gap-1.5">
                <Label class="text-sm font-bold">价格模式</Label>
                <Tabs
                  :model-value="settings.pricing_mode === 'coverage_tiered' ? 'coverage_tiered' : 'standard'"
                  @update:model-value="(value) => (settings.pricing_mode = value)"
                >
                  <TabsList class="h-10! w-full! sm:w-auto sm:grid-cols-2 sm:min-w-96">
                    <TabsTrigger value="standard" class="flex-1">标准页数计费</TabsTrigger>
                    <TabsTrigger value="coverage_tiered" class="flex-1">覆盖率阶梯计费</TabsTrigger>
                  </TabsList>
                </Tabs>
              </div>

              <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <div v-for="key in visiblePricingKeys" :key="key" class="grid gap-1.5">
                  <Label :for="`setting-${key}`" class="text-sm font-bold">{{ settingLabels[key] }}</Label>
                  <Input :id="`setting-${key}`" v-model="settings[key]" class="h-10" />
                </div>
              </div>
              <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <div v-for="key in commonSettingKeys" :key="key" class="grid gap-1.5">
                  <Label :for="`setting-${key}`" class="text-sm font-bold">{{ settingLabels[key] }}</Label>
                  <Input :id="`setting-${key}`" v-model="settings[key]" class="h-10" />
                </div>
              </div>

              <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <h3 class="font-display text-lg font-bold">批量打印折扣</h3>
                  <Button variant="secondary" size="sm" class="h-8" type="button" @click="addBulkDiscountRule">
                    <Plus />
                    新增规则
                  </Button>
                </div>
                <label class="flex w-fit cursor-pointer items-center gap-2 text-sm text-foreground">
                  <Checkbox v-model="settings.bulk_discount_enabled" />
                  启用批量打印折扣
                </label>
                <div v-for="(rule, index) in settings.bulk_discount_rules" :key="index" class="flex flex-wrap items-end gap-3">
                  <label class="grid flex-1 gap-1.5 sm:max-w-44">
                    <span class="text-[13px] font-semibold text-muted-foreground">满多少张</span>
                    <Input v-model.number="rule.min_sheets" type="number" min="1" step="1" class="h-9 bg-card" />
                  </label>
                  <label class="grid flex-1 gap-1.5 sm:max-w-44">
                    <span class="text-[13px] font-semibold text-muted-foreground">折扣（%）</span>
                    <Input v-model.number="rule.discount_percent" type="number" min="1" max="100" step="1" class="h-9 bg-card" />
                  </label>
                  <Button variant="destructive" size="sm" class="h-9" type="button" @click="removeBulkDiscountRule(index)">
                    <Trash2 />
                    删除规则
                  </Button>
                </div>
                <div v-if="!settings.bulk_discount_rules?.length" class="rounded-lg border border-dashed bg-card px-4 py-6 text-center text-sm text-muted-foreground">暂无批量折扣规则</div>
              </section>

              <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                <h3 class="font-display text-lg font-bold">每日限时特价</h3>
                <div class="flex flex-wrap gap-x-5 gap-y-3">
                  <label class="flex cursor-pointer items-center gap-2 text-sm text-foreground">
                    <Checkbox v-model="settings.daily_limited_offer_enabled" />
                    启用每日限时特价
                  </label>
                  <label class="flex cursor-pointer items-center gap-2 text-sm text-foreground">
                    <Checkbox v-model="settings.daily_limited_offer_all_day" />
                    全天生效
                  </label>
                  <label class="flex cursor-pointer items-center gap-2 text-sm text-foreground">
                    <Checkbox v-model="settings.daily_limited_offer_free" />
                    完全免费（0 元）
                  </label>
                </div>
                <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <label class="grid gap-1.5" :class="{ 'opacity-60': settings.daily_limited_offer_all_day }">
                    <span class="text-[13px] font-semibold text-muted-foreground">开始时间</span>
                    <Input v-model="settings.daily_limited_offer_start_time" type="time" :disabled="settings.daily_limited_offer_all_day" class="h-10 bg-card" />
                  </label>
                  <label class="grid gap-1.5" :class="{ 'opacity-60': settings.daily_limited_offer_all_day }">
                    <span class="text-[13px] font-semibold text-muted-foreground">结束时间</span>
                    <Input v-model="settings.daily_limited_offer_end_time" type="time" :disabled="settings.daily_limited_offer_all_day" class="h-10 bg-card" />
                  </label>
                  <label class="grid gap-1.5">
                    <span class="text-[13px] font-semibold text-muted-foreground">每日限购张数</span>
                    <Input v-model.number="settings.daily_limited_offer_sheet_quota" type="number" min="0" step="1" class="h-10 bg-card" />
                  </label>
                  <label class="grid gap-1.5" :class="{ 'opacity-60': settings.daily_limited_offer_free }">
                    <span class="text-[13px] font-semibold text-muted-foreground">特价折扣（%）</span>
                    <Input v-model.number="settings.daily_limited_offer_discount_percent" type="number" min="1" max="100" step="1" :disabled="settings.daily_limited_offer_free" class="h-10 bg-card" />
                  </label>
                </div>
                <small class="text-xs leading-relaxed text-muted-foreground">
                  限时特价按全站每日张数额度共享；当前订单张数超过剩余额度时不享受限时特价。勾选“全天生效”后忽略开始/结束时间，当日额度内全天享受特价。勾选“完全免费”后，命中额度的订单在生效时段内为 0 元并直接免支付派发打印，折扣百分比将被忽略。
                </small>
              </section>

              <Button class="h-10 w-fit" @click="saveSettings">
                <Save />
                保存设置
              </Button>
            </template>

            <!-- ============ 站点设置 ============ -->
            <template v-if="tab === 'site'">
              <div class="grid gap-1">
                <p class="text-[13px] font-bold tracking-widest text-primary">站点级配置</p>
                <h2 class="font-display text-2xl font-bold tracking-tight">站点设置</h2>
              </div>
              <small class="text-xs text-muted-foreground">以下配置前台与后台共用，保存后立即生效并持久化（刷新页面仍生效）。</small>

              <Tabs v-if="siteSettings !== null" default-value="lock">
                <TabsList class="h-10! w-full! sm:w-auto sm:grid-cols-4 sm:min-w-125">
                  <TabsTrigger value="lock" class="flex-1">登录锁定</TabsTrigger>
                  <TabsTrigger value="title" class="flex-1">网页标题</TabsTrigger>
                  <TabsTrigger value="favicon" class="flex-1">网站图标</TabsTrigger>
                  <TabsTrigger value="icp" class="flex-1">备案号</TabsTrigger>
                </TabsList>

                <!-- 3.1 登录锁定：连续失败 N 次锁定账号 + 锁定时长，保存即作用于登录接口 -->
                <TabsContent value="lock" class="grid gap-3 pt-4">
                  <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                    <div class="grid gap-3 sm:grid-cols-2">
                      <div class="grid gap-1.5">
                        <Label for="site-lock-threshold" class="text-sm font-bold">连续失败次数锁定账号</Label>
                        <Input id="site-lock-threshold" v-model.number="siteSettingsForm.login_lock_threshold" type="number" min="1" max="100" step="1" class="h-10 bg-card" />
                      </div>
                      <div class="grid gap-1.5">
                        <Label for="site-lock-minutes" class="text-sm font-bold">锁定时长（分钟）</Label>
                        <Input id="site-lock-minutes" v-model.number="siteSettingsForm.login_lock_minutes" type="number" min="1" max="1440" step="1" class="h-10 bg-card" />
                      </div>
                    </div>
                    <small class="text-xs leading-relaxed text-muted-foreground">
                      同一 IP + 用户名连续登录失败达到次数后锁定账号；锁定期间登录返回「账号已锁定，请 N 分钟后重试」，未锁定的登录失败会提示剩余可尝试次数。
                    </small>
                    <Button class="h-9 w-fit" @click="saveSiteSettingsGroup('lock')">
                      <Save />
                      保存登录锁定设置
                    </Button>
                  </section>
                </TabsContent>

                <!-- 3.2 网页标题：document.title + 默认标题，全站共用 -->
                <TabsContent value="title" class="grid gap-3 pt-4">
                  <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                    <div class="grid gap-1.5 sm:max-w-md">
                      <Label for="site-title" class="text-sm font-bold">网站标题</Label>
                      <Input id="site-title" v-model.trim="siteSettingsForm.site_title" maxlength="80" placeholder="PrintHub 云打印" class="h-10 bg-card" />
                      <small class="text-xs leading-relaxed text-muted-foreground">浏览器标签页标题，登录页 / 前台 / 后台共用；留空恢复默认「PrintHub 云打印」。</small>
                    </div>
                    <Button class="h-9 w-fit" @click="saveSiteSettingsGroup('title')">
                      <Save />
                      保存标题
                    </Button>
                  </section>
                </TabsContent>

                <!-- 3.3 网站图标：上传 .ico/.png 或填写外链 URL，动态替换 <link rel="icon"> -->
                <TabsContent value="favicon" class="grid gap-3 pt-4">
                  <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                    <div class="grid gap-1.5">
                      <Label class="text-sm font-bold">图标来源</Label>
                      <Tabs :model-value="siteSettingsForm.site_favicon_mode" @update:model-value="(value) => (siteSettingsForm.site_favicon_mode = value)">
                        <TabsList class="h-10! w-full! sm:w-auto sm:grid-cols-3 sm:min-w-72">
                          <TabsTrigger v-for="mode in siteFaviconModes" :key="mode.value" :value="mode.value" class="flex-1">{{ mode.label }}</TabsTrigger>
                        </TabsList>
                      </Tabs>
                    </div>
                    <input ref="siteFaviconInput" type="file" accept=".ico,.png" class="sr-only" @change="uploadSiteFavicon" />
                    <div v-if="siteSettingsForm.site_favicon_mode === 'upload'" class="flex flex-wrap items-center gap-3">
                      <span class="grid size-10 shrink-0 place-items-center rounded-md border bg-card p-1">
                        <img v-if="siteFaviconPreviewUrl" :src="siteFaviconPreviewUrl" alt="当前网站图标" class="size-full object-contain" />
                        <ImageIcon v-else class="size-4 text-muted-foreground" aria-hidden="true" />
                      </span>
                      <Button type="button" variant="secondary" class="h-9" :disabled="siteFaviconUploading" @click="siteFaviconInput?.click()">
                        <UploadCloud />
                        {{ siteFaviconUploading ? '上传中…' : siteFaviconPreviewUrl ? '重新上传图标' : '选择图标文件上传' }}
                      </Button>
                      <Badge v-if="siteFaviconPreviewUrl" class="border-transparent bg-success/10 text-success">已上传并生效</Badge>
                    </div>
                    <div v-else-if="siteSettingsForm.site_favicon_mode === 'url'" class="grid gap-1.5 sm:max-w-md">
                      <Label for="site-favicon-url" class="text-sm font-bold">图标 URL</Label>
                      <Input id="site-favicon-url" v-model.trim="siteSettingsForm.site_favicon_url" placeholder="https://example.com/favicon.ico" class="h-10 bg-card" />
                    </div>
                    <p v-else class="text-xs text-muted-foreground">未设置自定义图标，站点使用默认图标。</p>
                    <small class="text-xs leading-relaxed text-muted-foreground">
                      推荐使用 32×32 或 48×48 的正方形 .ico / .png 图标，文件不超过 200KB；上传后立即生效。填写 URL 保存后同样立即生效。
                    </small>
                    <Button class="h-9 w-fit" :disabled="siteFaviconUploading" @click="saveSiteSettingsGroup('favicon')">
                      <Save />
                      保存图标设置
                    </Button>
                  </section>
                </TabsContent>

                <!-- 3.4 备案号：留空不显示备案条；填写后全站底部显示并链接工信部备案网站 -->
                <TabsContent value="icp" class="grid gap-3 pt-4">
                  <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                    <div class="grid gap-1.5 sm:max-w-md">
                      <Label for="site-icp" class="text-sm font-bold">ICP 备案号</Label>
                      <Input id="site-icp" v-model.trim="siteSettingsForm.site_icp_number" maxlength="60" placeholder="例如：京ICP备2024000000号" class="h-10 bg-card" />
                      <small class="text-xs leading-relaxed text-muted-foreground">
                        填写后全站底部居中显示备案号（点击在新窗口打开工信部备案网站 beian.miit.gov.cn）；留空则全站不显示备案条。
                      </small>
                    </div>
                    <Button class="h-9 w-fit" @click="saveSiteSettingsGroup('icp')">
                      <Save />
                      保存备案号
                    </Button>
                  </section>
                </TabsContent>
              </Tabs>
            </template>

            <!-- ============ 支付 ============ -->
            <template v-if="tab === 'payment'">
              <h2 class="font-display text-2xl font-bold tracking-tight">易支付配置</h2>

              <Alert v-if="paymentSettings.validation" :class="paymentSettings.validation.ready
                ? 'border-success/30 bg-success/10 text-success'
                : 'border-warning/30 bg-warning/10 text-warning'">
                <CircleCheck v-if="paymentSettings.validation.ready" class="size-4" />
                <TriangleAlert v-else class="size-4" />
                <AlertTitle>{{ paymentSettings.validation.ready ? '易支付配置已就绪' : '易支付配置未就绪' }}</AlertTitle>
                <AlertDescription :class="paymentSettings.validation.ready ? 'text-success' : 'text-warning'">
                  <span v-for="item in paymentSettings.validation.errors || []" :key="item" class="block">{{ item }}</span>
                  <span v-for="item in paymentSettings.validation.warnings || []" :key="item" class="block">{{ item }}</span>
                </AlertDescription>
              </Alert>

              <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <div v-for="field in paymentFields" :key="field.key" class="grid gap-1.5">
                  <Label :for="`pay-${field.key}`" class="text-sm font-bold">{{ field.label }}</Label>
                  <Input
                    :id="`pay-${field.key}`"
                    v-model="paymentSettings[field.key]"
                    :type="field.type"
                    :placeholder="field.key === 'epay_key' ? paymentSettings.epay_key_masked : undefined"
                    class="h-10"
                  />
                </div>
              </div>
              <Button class="h-10 w-fit" @click="savePaymentSettings">
                <Save />
                保存支付配置
              </Button>

              <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                <div class="grid gap-1">
                  <p class="text-[13px] font-bold tracking-widest text-primary">支付自测</p>
                  <h3 class="font-display text-lg font-bold">创建测试支付单</h3>
                </div>
                <div class="grid gap-3 sm:grid-cols-2">
                  <div class="grid gap-1.5">
                    <Label class="text-sm font-bold">支付方式</Label>
                    <Select v-model="paymentTest.payment_method">
                      <SelectTrigger class="h-10 w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="alipay">支付宝</SelectItem>
                        <SelectItem value="wxpay">微信</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div class="grid gap-1.5">
                    <Label class="text-sm font-bold">测试金额</Label>
                    <Input v-model.number="paymentTest.amount" type="number" min="0.01" step="0.01" class="h-10" />
                  </div>
                </div>
                <div class="flex flex-wrap gap-2">
                  <Button variant="secondary" class="h-9 flex-1 sm:flex-none" :disabled="paymentSettings.validation && !paymentSettings.validation.ready" @click="createPaymentTest">
                    <CreditCard />
                    发起测试支付
                  </Button>
                  <Button variant="secondary" class="h-9 flex-1 sm:flex-none" :disabled="!paymentTestResult?.payment_url || paymentTestResult?.status !== 'pending'" @click="openPaymentTest">
                    <ExternalLink />
                    打开测试支付页
                  </Button>
                  <Button variant="secondary" class="h-9 flex-1 sm:flex-none" :disabled="!paymentTestResult?.order_id" @click="refreshPaymentTest">
                    <RefreshCw />
                    刷新测试状态
                  </Button>
                  <Button variant="secondary" class="h-9 flex-1 sm:flex-none" :disabled="!paymentTestResult?.order_id || paymentTestResult?.status !== 'pending'" @click="simulatePaymentTestSuccess">
                    <CheckCircle />
                    模拟支付成功
                  </Button>
                </div>
                <div v-if="paymentTestResult" class="grid gap-2 rounded-lg border bg-card p-3.5 text-sm">
                  <strong class="text-foreground">测试单 {{ paymentTestResult.order_id }}</strong>
                  <span class="text-muted-foreground">金额 ¥{{ Number(paymentTestResult.amount || 0).toFixed(2) }} · {{ formatPaymentMethod(paymentTestResult.payment_method) }} · {{ paymentTestResult.gateway || '本地测试单' }}</span>
                  <div class="flex flex-wrap gap-2">
                    <Badge :class="statusBadgeClass(paymentTestStatusClass(paymentTestResult.status))">订单 {{ formatPaymentStatus(paymentTestResult.status) }}</Badge>
                    <Badge :class="statusBadgeClass(paymentTestStatusClass(paymentTestResult.payment_status))">支付 {{ formatPaymentStatus(paymentTestResult.payment_status) }}</Badge>
                    <Badge v-if="paymentTestResult.paid_at" class="border-transparent bg-success/10 text-success">已回调 {{ paymentTestResult.paid_at }}</Badge>
                  </div>
                  <small class="break-all text-xs text-muted-foreground">提交地址 {{ paymentTestResult.payment_url }} · 签名类型 {{ paymentTestResult.params?.sign_type || 'MD5' }} · 支付类型 {{ paymentTestResult.params?.type || paymentTestResult.payment_method }}</small>
                </div>
              </section>
            </template>

            <!-- ============ 打印机 ============ -->
            <template v-if="tab === 'printers'">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div class="grid gap-1">
                  <p class="text-[13px] font-bold tracking-widest text-primary">打印机管理</p>
                  <h2 class="font-display text-2xl font-bold tracking-tight">打印机</h2>
                </div>
                <Button variant="secondary" class="h-9" @click="loadTab">
                  <RefreshCw />
                  刷新
                </Button>
              </div>

              <div class="grid gap-3 sm:grid-cols-3">
                <div v-for="stat in printerStatCards" :key="stat.label" class="flex items-center gap-3 rounded-xl border bg-card p-4">
                  <span class="grid size-10 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground" :class="stat.iconClass || ''">
                    <component :is="stat.icon" class="size-5" />
                  </span>
                  <div class="grid min-w-0 gap-0.5">
                    <span class="text-[13px] text-muted-foreground">{{ stat.label }}</span>
                    <strong class="truncate text-sm font-bold text-foreground">{{ stat.value }}</strong>
                  </div>
                </div>
              </div>

              <div v-if="printerSystem.diagnostics?.length" class="grid gap-1 rounded-lg border border-warning/30 bg-warning/10 p-3">
                <small v-for="item in printerSystem.diagnostics" :key="`${item.source}-${item.message}`" class="text-xs leading-relaxed text-warning">
                  {{ item.message }} {{ item.hint }}
                </small>
              </div>

              <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                <h3 class="font-display text-lg font-bold">CUPS 服务器配置</h3>
                <div class="grid gap-1.5 sm:max-w-md">
                  <Label for="cups-server" class="text-sm font-bold">{{ settingLabels.cups_server }}</Label>
                  <Input id="cups-server" v-model="settings.cups_server" placeholder="例如: 192.168.1.100:631" class="h-10" />
                </div>
                <small class="text-xs leading-relaxed text-muted-foreground">
                  保存后会自动刷新打印机列表与默认打印机状态。CUPS 服务器地址格式为: 主机名:端口 或 IP:端口，默认端口为 631。
                </small>
                <Button class="h-10 w-fit" @click="saveSettings({ reloadPrinters: true })">
                  <Save />
                  保存配置
                </Button>
              </section>

              <div class="grid gap-3">
                <div v-if="printers.length === 0" class="grid place-items-center gap-2 rounded-xl border border-dashed bg-muted/40 px-4 py-10 text-center text-muted-foreground">
                  <Printer class="size-12 opacity-50" aria-hidden="true" />
                  <p class="text-sm font-semibold">暂无打印机</p>
                  <p class="text-xs">请在 CUPS 服务器上添加打印机后刷新列表</p>
                </div>
                <div v-else class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  <Card v-for="printer in printers" :key="printer.name" class="gap-3 py-4">
                    <CardHeader class="flex-row items-start justify-between gap-2 pb-0">
                      <Badge :class="printerStateClass(printer.state)">
                        {{ printer.state === 'idle' ? '空闲' : printer.state === 'processing' ? '打印中' : printer.state === 'stopped' ? '已停止' : '未知' }}
                      </Badge>
                      <Badge v-if="printer.is_default" class="border-transparent bg-primary text-primary-foreground">默认</Badge>
                    </CardHeader>
                    <CardContent class="grid gap-2.5">
                      <div class="grid gap-0.5">
                        <h3 class="break-all font-display text-base font-bold text-foreground">{{ printer.display_name || printer.name }}</h3>
                        <p class="break-all text-[13px] text-muted-foreground">{{ printer.driver_label || printer.driver }}</p>
                      </div>
                      <div class="grid gap-1 text-xs text-muted-foreground">
                        <span class="flex min-w-0 items-center gap-1.5"><Globe class="size-3.5 shrink-0" /><span class="break-all">{{ printer.uri || '未配置' }}</span></span>
                        <span class="flex items-center gap-1.5"><MapPin class="size-3.5 shrink-0" /><span class="break-all">{{ printer.location || '未指定位置' }}</span></span>
                      </div>
                      <div class="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
                        <span>队列任务：{{ printer.queued_jobs || 0 }}</span>
                        <span>状态：{{ printer.is_enabled ? '启用' : '停用' }}</span>
                      </div>
                      <!-- 【新增功能】打印机能力标识：这两个开关决定前台是否展示「彩色打印」「自动双面打印」。 -->
                      <div class="flex flex-wrap gap-2">
                        <Badge variant="outline" :class="printer.is_support_color ? 'border-fuchsia-500/0 bg-accent text-accent-foreground' : ''">
                          <span class="size-2 rounded-full" :style="{ background: printer.is_support_color ? 'var(--chart-5)' : 'var(--border)' }" aria-hidden="true"></span>
                          {{ printer.is_support_color ? '支持彩色打印' : '仅黑白打印' }}
                        </Badge>
                        <Badge variant="outline" :class="printer.is_support_auto_duplex ? 'bg-accent text-accent-foreground' : ''">
                          <span class="size-2 rounded-full" :style="{ background: printer.is_support_auto_duplex ? 'var(--chart-3)' : 'var(--border)' }" aria-hidden="true"></span>
                          {{ printer.is_support_auto_duplex ? '支持自动双面' : '仅单面打印' }}
                        </Badge>
                      </div>
                      <div class="flex gap-2 pt-0.5">
                        <Button variant="outline" size="icon-sm" class="max-md:size-9" title="编辑打印机（彩色 / 自动双面能力）" @click="openPrinterEditor(printer)">
                          <Pencil />
                        </Button>
                        <Button v-if="!printer.is_default" variant="outline" size="icon-sm" class="max-md:size-9" title="设置默认打印机" @click="makeDefault(printer.name)">
                          <CheckCircle />
                        </Button>
                        <Button v-else variant="outline" size="icon-sm" class="max-md:size-9" title="取消默认打印机" @click="clearDefault()">
                          <XCircle />
                        </Button>
                        <Button variant="outline" size="icon-sm" class="max-md:size-9" title="打印测试" @click="testPrint(printer.name)">
                          <Printer />
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </div>

              <section v-if="selectedPrinterInfo" class="grid gap-3 rounded-xl border border-primary/25 bg-accent/40 p-4">
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div class="grid gap-1">
                    <p class="text-[13px] font-bold tracking-widest text-primary">实时状态</p>
                    <h3 class="break-all font-display text-lg font-bold">{{ selectedPrinterInfo.name }}</h3>
                  </div>
                  <Button variant="secondary" class="h-9" @click="selectedPrinterInfo = null">
                    <RotateCcw />
                    收起
                  </Button>
                </div>
                <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <div v-for="stat in printerInfoStats" :key="stat.label" class="rounded-lg border bg-card p-3">
                    <span class="block text-xs text-muted-foreground">{{ stat.label }}</span>
                    <strong class="text-sm font-bold text-foreground">{{ stat.value }}</strong>
                  </div>
                </div>
                <div class="flex flex-wrap gap-2">
                  <Badge v-for="reason in selectedPrinterInfo.state_reasons || []" :key="reason" variant="outline">{{ reason }}</Badge>
                  <Badge v-for="media in selectedPrinterInfo.media_ready || []" :key="media" class="border-transparent bg-success/10 text-success">{{ media }}</Badge>
                </div>
                <div v-if="selectedPrinterJobs.length" class="grid gap-2">
                  <h4 class="text-sm font-bold text-foreground">队列任务</h4>
                  <div v-for="job in selectedPrinterJobs" :key="job.id" class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 rounded-lg border bg-card px-3 py-2 text-sm">
                    <strong class="break-all text-foreground">#{{ job.id }} {{ job.title }}</strong>
                    <span class="text-xs text-muted-foreground">{{ job.state_text || job.state }} · {{ formatDateTime(job.created_at) }} · {{ Math.round((job.size || 0) / 1024) }} KB</span>
                  </div>
                </div>
              </section>
            </template>

            <!-- ============ 备份 ============ -->
            <template v-if="tab === 'backups'">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div class="grid gap-1">
                  <p class="text-[13px] font-bold tracking-widest text-primary">数据安全</p>
                  <h2 class="font-display text-2xl font-bold tracking-tight">备份与恢复</h2>
                </div>
                <Button variant="secondary" class="h-9" @click="loadTab">
                  <RefreshCw />
                  刷新
                </Button>
              </div>

              <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div class="grid gap-1">
                    <p class="text-[13px] font-bold tracking-widest text-primary">一键备份</p>
                    <h3 class="font-display text-lg font-bold">创建完整数据包</h3>
                  </div>
                  <Tabs :model-value="backupCreate.archive_format" @update:model-value="(value) => (backupCreate.archive_format = value)">
                    <TabsList class="h-9!">
                      <TabsTrigger value="zip" class="px-4">ZIP</TabsTrigger>
                      <TabsTrigger value="tar.gz" class="px-4">TAR.GZ</TabsTrigger>
                    </TabsList>
                  </Tabs>
                </div>
                <div class="grid gap-2 sm:grid-cols-3">
                  <div v-for="item in backupSummary" :key="item.title" class="rounded-lg border bg-card p-3">
                    <strong class="block text-sm text-foreground">{{ item.title }}</strong>
                    <span class="text-xs text-muted-foreground">{{ item.desc }}</span>
                  </div>
                </div>
                <Button class="h-10 w-fit" :disabled="backupBusy" @click="createBackup">
                  <Archive />
                  {{ backupBusy ? '正在备份' : '立即备份' }}
                </Button>
              </section>

              <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                <div class="grid gap-1">
                  <p class="text-[13px] font-bold tracking-widest text-primary">自动备份</p>
                  <h3 class="font-display text-lg font-bold">执行策略</h3>
                </div>
                <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <div class="grid gap-1.5">
                    <Label class="text-sm font-bold">执行频率</Label>
                    <Select v-model="backupPolicy.frequency">
                      <SelectTrigger class="h-10 w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="daily">每天</SelectItem>
                        <SelectItem value="weekly">每周</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div class="grid gap-1.5">
                    <Label for="backup-time" class="text-sm font-bold">执行时间</Label>
                    <Input id="backup-time" v-model="backupPolicy.time" type="time" class="h-10" />
                  </div>
                  <div v-if="backupPolicy.frequency === 'weekly'" class="grid gap-1.5">
                    <Label class="text-sm font-bold">每周几</Label>
                    <Select :model-value="String(backupPolicy.weekday)" @update:model-value="(value) => (backupPolicy.weekday = Number(value))">
                      <SelectTrigger class="h-10 w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem v-for="(label, index) in weekdayLabels" :key="label" :value="String(index)">{{ label }}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div class="grid gap-1.5">
                    <Label for="backup-retention" class="text-sm font-bold">保留数量</Label>
                    <Input id="backup-retention" v-model.number="backupPolicy.retention_count" type="number" min="1" max="365" step="1" class="h-10" />
                  </div>
                </div>
                <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
                  <label class="flex cursor-pointer items-center gap-2 text-sm text-foreground">
                    <Checkbox v-model="backupPolicy.enabled" />
                    启用自动备份
                  </label>
                  <Button class="h-9" @click="saveBackupPolicy">
                    <Save />
                    保存策略
                  </Button>
                  <span class="text-xs text-muted-foreground">上次执行：{{ backupPolicy.last_run_at || '尚未执行' }}</span>
                </div>
              </section>

              <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
                <div class="grid gap-1">
                  <p class="text-[13px] font-bold tracking-widest text-primary">恢复数据</p>
                  <h3 class="font-display text-lg font-bold">上传备份文件</h3>
                </div>
                <label
                  class="flex cursor-pointer flex-col items-center justify-center gap-2.5 rounded-xl border-2 border-dashed border-border px-6 py-9 text-center text-primary transition-colors hover:border-primary hover:bg-accent/70"
                  :class="restoreDragging ? 'border-solid border-primary bg-accent' : ''"
                  @dragover.prevent="restoreDragging = true"
                  @dragleave.prevent="restoreDragging = false"
                  @drop.prevent="dropRestoreFile"
                >
                  <UploadCloud class="size-7" />
                  <span class="text-sm font-bold">拖拽备份文件到这里，或点击选择</span>
                  <small class="text-xs text-muted-foreground">支持 backup_*.zip 和 backup_*.tar.gz；恢复前会解析校验备份完整性</small>
                  <input type="file" accept=".zip,.tar.gz,.tgz" class="sr-only" @change="chooseRestoreFile" />
                </label>
                <div v-if="restoreInfo" class="grid gap-2.5 rounded-xl border border-primary/25 bg-accent/60 p-4">
                  <strong class="break-all text-sm text-foreground">{{ restoreInfo.filename }}</strong>
                  <span class="text-[13px] text-muted-foreground">
                    备份时间：{{ formatDateTime(restoreInfo.backup_time) }} · 数据版本：{{ restoreInfo.data_version }} · 格式：{{ restoreInfo.archive_format }}
                  </span>
                  <div class="flex flex-wrap gap-2">
                    <Badge class="border-transparent bg-success/10 text-success">数据库</Badge>
                    <Badge :class="restoreInfo.content?.uploads ? 'border-transparent bg-success/10 text-success' : ''" :variant="restoreInfo.content?.uploads ? undefined : 'secondary'">上传文件 {{ restoreInfo.content?.uploads ? '包含' : '未包含' }}</Badge>
                    <Badge :class="restoreInfo.content?.logs ? 'border-transparent bg-success/10 text-success' : ''" :variant="restoreInfo.content?.logs ? undefined : 'secondary'">日志 {{ restoreInfo.content?.logs ? '包含' : '未包含' }}</Badge>
                    <Badge variant="outline">配置 {{ restoreInfo.content?.config_files?.length || 0 }} 个</Badge>
                  </div>
                  <Button variant="destructive" class="h-10 w-fit" :disabled="restoreBusy" @click="restoreBackup">
                    <RotateCcw />
                    确认覆盖并恢复
                  </Button>
                </div>
              </section>

              <section class="grid gap-2">
                <div class="grid gap-1">
                  <p class="text-[13px] font-bold tracking-widest text-primary">备份列表</p>
                  <h3 class="font-display text-lg font-bold">可下载归档</h3>
                </div>
                <div v-for="backup in backups" :key="backup.filename" class="grid gap-2.5 rounded-xl border bg-card p-3.5 lg:grid-cols-[minmax(0,1fr)_auto]">
                  <div class="grid min-w-0 gap-1">
                    <strong class="break-all text-sm font-bold text-foreground">{{ backup.filename }}</strong>
                    <span class="text-[13px] text-muted-foreground">{{ formatDateTime(backup.backup_time) }} · {{ backup.data_version }} · {{ backup.archive_format }}</span>
                    <small class="text-xs text-muted-foreground">{{ backup.created_by === 'auto' ? '自动备份' : '手动备份' }} · {{ Number(backup.size_mb || 0).toFixed(2) }} MB</small>
                    <div class="flex flex-wrap gap-2 pt-0.5">
                      <Badge class="border-transparent bg-success/10 text-success">数据库</Badge>
                      <Badge v-if="backup.content?.uploads" variant="outline">上传文件</Badge>
                      <Badge v-if="backup.content?.logs" variant="outline">日志</Badge>
                      <Badge v-if="backup.content?.config_files?.length" variant="outline">配置</Badge>
                    </div>
                  </div>
                  <div class="flex flex-wrap items-start gap-2 lg:justify-end">
                    <Button variant="secondary" size="sm" class="h-8" @click="downloadBackup(backup)">
                      <Download />
                      下载
                    </Button>
                    <Button variant="destructive" size="sm" class="h-8" @click="deleteBackup(backup)">
                      <Trash2 />
                      删除
                    </Button>
                  </div>
                </div>
                <div v-if="backups.length === 0" class="rounded-lg border border-dashed bg-muted/40 px-4 py-8 text-center text-sm text-muted-foreground">暂无备份</div>
              </section>
            </template>

            <!-- ============ 兑换码 ============ -->
            <template v-if="tab === 'redemptions'">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div class="grid gap-1">
                  <p class="text-[13px] font-bold tracking-widest text-primary">兑换码</p>
                  <h2 class="font-display text-2xl font-bold tracking-tight">兑换码管理</h2>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <Input v-model.trim="redemptionSearch" placeholder="搜索兑换码" class="h-9 w-full max-w-44 sm:w-44" @keyup.enter="loadRedemptions" />
                  <Button variant="secondary" class="h-9" @click="openAddRedemption">
                    <Plus />
                    手动新增
                  </Button>
                  <Button variant="secondary" class="h-9" @click="openBatchRedemption">
                    <RefreshCw />
                    批量生成
                  </Button>
                </div>
              </div>

              <!-- 桌面端表格（md+） -->
              <div class="hidden overflow-hidden rounded-xl border md:block">
                <Table>
                  <TableHeader>
                    <TableRow class="bg-muted/60">
                      <TableHead>兑换码</TableHead>
                      <TableHead>兑换面额</TableHead>
                      <TableHead>有效期</TableHead>
                      <TableHead>使用状态</TableHead>
                      <TableHead class="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    <TableRow v-for="code in redemptions" :key="code.id">
                      <TableCell><strong class="break-all text-foreground" :title="code.code">{{ code.code }}</strong></TableCell>
                      <TableCell><strong class="font-display text-primary tabular-nums">¥{{ Number(code.amount).toFixed(2) }}</strong></TableCell>
                      <TableCell class="text-muted-foreground">{{ redemptionExpiryText(code) }}</TableCell>
                      <TableCell>
                        <Badge :class="statusBadgeClass(redemptionStatusClass(code.status))">{{ redemptionStatusLabel(code.status) }}</Badge>
                      </TableCell>
                      <TableCell>
                        <div class="flex justify-end gap-2">
                          <Button variant="secondary" size="sm" class="h-8" @click="openRedemptionDetail(code)">
                            <Eye />
                            详情
                          </Button>
                          <Button variant="destructive" size="sm" class="h-8" @click="deleteRedemption(code)">
                            <Trash2 />
                            删除
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                    <TableRow v-if="redemptions.length === 0">
                      <TableCell colspan="5" class="py-8 text-center text-muted-foreground">暂无兑换码</TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </div>

              <!-- 手机端列表（< md） -->
              <div class="grid gap-2 md:hidden">
                <div v-for="code in redemptions" :key="code.id" class="grid gap-1.5 rounded-xl border bg-card p-3.5 text-sm">
                  <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                    <strong class="break-all text-foreground" :title="code.code">{{ code.code }}</strong>
                    <strong class="font-display text-primary tabular-nums">¥{{ Number(code.amount).toFixed(2) }}</strong>
                  </div>
                  <div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <span class="text-[13px] text-muted-foreground">{{ redemptionExpiryText(code) }}</span>
                    <Badge :class="statusBadgeClass(redemptionStatusClass(code.status))">{{ redemptionStatusLabel(code.status) }}</Badge>
                  </div>
                  <div class="flex gap-2 pt-0.5">
                    <Button variant="secondary" size="sm" class="h-9 flex-1" @click="openRedemptionDetail(code)">
                      <Eye />
                      详情
                    </Button>
                    <Button variant="destructive" size="sm" class="h-9 flex-1" @click="deleteRedemption(code)">
                      <Trash2 />
                      删除
                    </Button>
                  </div>
                </div>
                <div v-if="redemptions.length === 0" class="rounded-lg border border-dashed bg-muted/40 px-4 py-8 text-center text-sm text-muted-foreground">暂无兑换码</div>
              </div>

              <div v-if="redemptionsHasMore" class="grid">
                <Button variant="secondary" class="h-10 w-full max-w-xs justify-self-center" @click="loadMoreRedemptions" :disabled="redemptionLoadingMore">
                  {{ redemptionLoadingMore ? '加载中...' : '加载更多' }}
                </Button>
              </div>
            </template>
          </CardContent>
        </Card>

        <!-- 后台路由的 ICP 备案条：App.vue 在 /admin 下不渲染全局备案条，由这里在内容底部补上 -->
        <IcpFooter />
      </div>
    </SidebarInset>

    <!-- 手机端（< md）底部 Tab 栏：后台共 8 个 Tab，常用 4 个常驻，其余收进「更多」面板 -->
    <nav class="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-border bg-background/92 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden" aria-label="后台导航">
      <button
        v-for="item in primaryTabs"
        :key="item.key"
        type="button"
        class="flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold transition-colors"
        :class="tab === item.key ? 'text-primary' : 'text-muted-foreground active:text-foreground'"
        @click="selectTab(item.key)"
      >
        <span class="grid h-7 w-12 place-items-center rounded-full" :class="tab === item.key ? 'bg-primary/10' : ''">
          <component :is="item.icon" class="size-5" />
        </span>
        <span class="leading-none">{{ item.label }}</span>
      </button>
      <button
        type="button"
        class="flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold transition-colors"
        :class="moreActive ? 'text-primary' : 'text-muted-foreground active:text-foreground'"
        aria-haspopup="dialog"
        :aria-expanded="moreOpen ? 'true' : 'false'"
        @click="moreOpen = !moreOpen"
      >
        <span class="grid h-7 w-12 place-items-center rounded-full" :class="moreActive ? 'bg-primary/10' : ''">
          <component :is="moreCurrent ? moreCurrent.icon : MoreHorizontal" class="size-5" />
        </span>
        <span class="leading-none">{{ moreCurrent ? moreCurrent.label : '更多' }}</span>
      </button>
    </nav>

    <!-- 「更多」底部抽屉 -->
    <Sheet :open="moreOpen" @update:open="(value) => (moreOpen = value)">
      <SheetContent side="bottom" class="max-sm:max-h-[80dvh] rounded-t-2xl px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-4">
        <SheetHeader class="flex-row items-center justify-between pb-1">
          <SheetTitle class="font-display text-base">更多功能</SheetTitle>
          <SheetClose class="grid size-8 place-items-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="关闭">
            <X class="size-4" />
          </SheetClose>
        </SheetHeader>
        <div class="grid gap-2">
          <button
            v-for="item in moreTabs"
            :key="item.key"
            type="button"
            class="flex min-h-11 items-center gap-2.5 rounded-lg border bg-card px-3.5 text-sm font-semibold transition-colors"
            :class="tab === item.key ? 'border-primary text-primary bg-accent' : 'border-border text-muted-foreground hover:bg-muted'"
            @click="selectTab(item.key)"
          >
            <component :is="item.icon" class="size-4.5" />
            <span>{{ item.label }}</span>
          </button>
          <Button as-child variant="secondary" class="min-h-11">
            <RouterLink to="/">返回前台首页</RouterLink>
          </Button>
        </div>
      </SheetContent>
    </Sheet>

    <!-- 编辑打印机弹窗 -->
    <Dialog :open="showAddPrinterModal" @update:open="(value) => !value && closeAddPrinterModal()">
      <DialogContent class="max-h-[90dvh] overflow-y-auto max-sm:max-w-[calc(100vw-1.5rem)] sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>编辑打印机</DialogTitle>
          <DialogDescription>修改打印机 URI、驱动、位置与能力开关</DialogDescription>
        </DialogHeader>
        <form @submit.prevent="savePrinter" class="grid gap-3">
          <div class="grid gap-1.5">
            <Label for="printer-name" class="text-sm font-bold">队列名称</Label>
            <Input id="printer-name" v-model="printerForm.name" readonly class="h-10" />
          </div>
          <div class="grid gap-1.5">
            <Label for="printer-uri" class="text-sm font-bold">设备 URI</Label>
            <Input id="printer-uri" v-model="printerForm.uri" class="h-10" />
          </div>
          <div class="grid gap-1.5">
            <Label for="printer-driver" class="text-sm font-bold">驱动</Label>
            <Select v-model="printerForm.driver">
              <SelectTrigger id="printer-driver" class="h-10 w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem v-for="driver in printerDrivers" :key="driver.id" :value="driver.id">
                  {{ driver.recommended ? '★ ' : '' }}{{ driver.label }}{{ driver.source === 'local-ppd' ? ' (已导入)' : '' }}
                </SelectItem>
              </SelectContent>
            </Select>
            <small v-if="selectedPrinterDriver?.recommendation_reason" class="text-xs text-muted-foreground">{{ selectedPrinterDriver.recommendation_reason }}</small>
          </div>
          <div class="grid gap-1.5">
            <Label for="printer-location" class="text-sm font-bold">位置</Label>
            <Input id="printer-location" v-model="printerForm.location" placeholder="例如：会议室 A" class="h-10" />
          </div>
          <div class="grid gap-1.5">
            <Label for="printer-description" class="text-sm font-bold">说明</Label>
            <Input id="printer-description" v-model="printerForm.description" placeholder="打印机描述" class="h-10" />
          </div>
          <div class="grid gap-2.5">
            <label class="flex cursor-pointer items-center gap-2 text-sm text-foreground">
              <Checkbox v-model="printerForm.is_default" />
              设置为默认打印机
            </label>
            <label class="flex cursor-pointer items-center gap-2 text-sm text-foreground">
              <Checkbox v-model="printerForm.is_enabled" />
              启用打印机
            </label>
            <label class="flex cursor-pointer items-center gap-2 text-sm text-foreground">
              <Checkbox v-model="printerForm.accepting_jobs" />
              接收打印任务
            </label>
          </div>

          <!-- 【新增功能】打印机能力：持久化到 printers 表，并决定前台打印页是否展示对应选项。 -->
          <div class="grid gap-3 rounded-xl border bg-muted/50 p-3.5">
            <span class="text-sm font-bold text-foreground">打印机能力</span>
            <label class="flex cursor-pointer items-start gap-3">
              <Switch v-model="printerForm.is_support_color" class="mt-0.5" />
              <span class="grid gap-0.5">
                <strong class="inline-flex items-center gap-1.5 text-sm text-foreground">
                  <span class="size-2.5 rounded-full" :style="{ background: 'var(--chart-5)' }" aria-hidden="true"></span>
                  支持彩色打印
                </strong>
                <small class="text-xs leading-relaxed text-muted-foreground">
                  开启后前台展示「彩色打印」，勾选彩色时文件按原始色彩直接送印；关闭后前台完全隐藏该选项，并按黑白流程处理。
                </small>
              </span>
            </label>
            <label class="flex cursor-pointer items-start gap-3">
              <Switch v-model="printerForm.is_support_auto_duplex" class="mt-0.5" />
              <span class="grid gap-0.5">
                <strong class="inline-flex items-center gap-1.5 text-sm text-foreground">
                  <span class="size-2.5 rounded-full" :style="{ background: 'var(--chart-3)' }" aria-hidden="true"></span>
                  支持自动双面打印
                </strong>
                <small class="text-xs leading-relaxed text-muted-foreground">
                  开启后前台展示「自动双面」；关闭后前台完全隐藏该选项，所有任务按单面打印。
                </small>
              </span>
            </label>
          </div>

          <DialogFooter class="gap-2">
            <Button type="button" variant="secondary" class="h-10" @click="closeAddPrinterModal">取消</Button>
            <Button type="submit" class="h-10">保存修改</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>

    <!-- 手动新增兑换码 -->
    <Dialog :open="showAddRedemptionModal" @update:open="(value) => !value && closeAddRedemptionModal()">
      <DialogContent class="max-h-[90dvh] overflow-y-auto max-sm:max-w-[calc(100vw-1.5rem)] sm:max-w-md">
        <DialogHeader>
          <DialogTitle>手动新增兑换码</DialogTitle>
          <DialogDescription>创建单个兑换码，支持指定有效期与单用户使用上限</DialogDescription>
        </DialogHeader>
        <form @submit.prevent="saveAddRedemption" class="grid gap-3">
          <div class="grid gap-1.5">
            <Label for="redemption-code" class="text-sm font-bold">兑换码</Label>
            <Input id="redemption-code" v-model.trim="redemptionForm.code" placeholder="自定义兑换码（留空随机生成）" maxlength="64" class="h-10" />
          </div>
          <div class="grid gap-1.5">
            <Label for="redemption-amount" class="text-sm font-bold">兑换面额（元）</Label>
            <Input id="redemption-amount" v-model.number="redemptionForm.amount" type="number" min="0.01" step="0.01" required class="h-10" />
          </div>
          <div class="grid gap-1.5">
            <Label for="redemption-count" class="text-sm font-bold">可用次数</Label>
            <Input id="redemption-count" v-model.number="redemptionForm.usable_count" type="number" min="1" step="1" class="h-10" />
          </div>
          <!-- 【新增功能】有效期支持「按天数」或「直接指定到期日期」两种互斥方式 -->
          <div class="grid gap-1.5">
            <Label class="text-sm font-bold">有效期</Label>
            <Tabs :model-value="redemptionForm.expiry_mode" @update:model-value="(value) => (redemptionForm.expiry_mode = value)">
              <TabsList class="h-9! w-full!">
                <TabsTrigger value="days" class="flex-1">按天数</TabsTrigger>
                <TabsTrigger value="date" class="flex-1">指定到期日期</TabsTrigger>
              </TabsList>
            </Tabs>
            <Input
              v-if="redemptionForm.expiry_mode === 'days'"
              v-model.number="redemptionForm.valid_days"
              type="number"
              min="0"
              step="1"
              placeholder="0 表示永久有效"
              class="h-10"
            />
            <Input v-else v-model="redemptionForm.expire_date" type="date" class="h-10" />
            <p class="text-xs text-muted-foreground">{{ redemptionExpiryHint }}</p>
          </div>
          <!-- 【单用户使用限制】开关关闭时数字输入框禁用；开启后提交正整数 -->
          <section class="grid gap-2.5 rounded-xl border bg-muted/50 p-3.5">
            <h4 class="text-sm font-bold text-foreground">单用户使用限制</h4>
            <div class="flex flex-wrap items-center justify-between gap-3">
              <label class="flex cursor-pointer items-center gap-2.5 text-sm text-foreground">
                <Switch v-model="redemptionForm.per_user_limit_enabled" />
                开启单用户次数限制
              </label>
              <label class="grid gap-1 text-xs text-muted-foreground">
                <span>最大使用次数</span>
                <Input
                  v-model.number="redemptionForm.per_user_max_times"
                  type="number"
                  min="1"
                  step="1"
                  :disabled="!redemptionForm.per_user_limit_enabled"
                  placeholder="请输入正整数"
                  class="h-9 w-36"
                />
              </label>
            </div>
            <p class="text-xs leading-relaxed text-muted-foreground">开启后，同一用户最多可使用该兑换码 {{ perUserMaxTimesHint }} 次。</p>
          </section>
          <DialogFooter class="gap-2">
            <Button type="button" variant="secondary" class="h-10" @click="closeAddRedemptionModal">取消</Button>
            <Button type="submit" class="h-10" :disabled="redemptionSaving">{{ redemptionSaving ? '保存中...' : '创建兑换码' }}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>

    <!-- 批量生成兑换码 -->
    <Dialog :open="showBatchRedemptionModal" @update:open="(value) => !value && closeBatchRedemptionModal()">
      <DialogContent class="max-h-[90dvh] overflow-y-auto max-sm:max-w-[calc(100vw-1.5rem)] sm:max-w-md">
        <DialogHeader>
          <DialogTitle>批量生成兑换码</DialogTitle>
          <DialogDescription>批量生成相同面额与有效期的兑换码</DialogDescription>
        </DialogHeader>
        <form @submit.prevent="saveBatchRedemption" class="grid gap-3">
          <div class="grid gap-1.5">
            <Label for="batch-count" class="text-sm font-bold">生成数量</Label>
            <Input id="batch-count" v-model.number="batchRedemptionForm.count" type="number" min="1" max="1000" step="1" class="h-10" />
          </div>
          <div class="grid gap-1.5">
            <Label for="batch-amount" class="text-sm font-bold">单张面额（元）</Label>
            <Input id="batch-amount" v-model.number="batchRedemptionForm.amount" type="number" min="0.01" step="0.01" required class="h-10" />
          </div>
          <div class="grid gap-1.5">
            <Label for="batch-usable" class="text-sm font-bold">可用次数</Label>
            <Input id="batch-usable" v-model.number="batchRedemptionForm.usable_count" type="number" min="1" step="1" class="h-10" />
          </div>
          <!-- 【新增功能】批量生成同样支持「按天数」/「指定到期日期」二选一，与手动新增一致。 -->
          <div class="grid gap-1.5">
            <Label class="text-sm font-bold">有效期</Label>
            <Tabs :model-value="batchRedemptionForm.expiry_mode" @update:model-value="(value) => (batchRedemptionForm.expiry_mode = value)">
              <TabsList class="h-9! w-full!">
                <TabsTrigger value="days" class="flex-1">按天数</TabsTrigger>
                <TabsTrigger value="date" class="flex-1">指定到期日期</TabsTrigger>
              </TabsList>
            </Tabs>
            <Input
              v-if="batchRedemptionForm.expiry_mode === 'days'"
              v-model.number="batchRedemptionForm.valid_days"
              type="number"
              min="0"
              step="1"
              placeholder="0 表示永久有效"
              class="h-10"
            />
            <Input v-else v-model="batchRedemptionForm.expire_date" type="date" class="h-10" />
            <p class="text-xs text-muted-foreground">{{ batchRedemptionExpiryHint }}</p>
          </div>
          <div v-if="batchResult.length" class="grid gap-2 rounded-xl border bg-muted/50 p-3.5">
            <div class="flex items-center justify-between gap-3">
              <strong class="text-sm text-foreground">已生成 {{ batchResult.length }} 个兑换码</strong>
              <Button type="button" variant="secondary" size="sm" class="h-8" @click="copyBatchResult">复制全部</Button>
            </div>
            <div class="flex max-h-32 flex-wrap gap-1.5 overflow-y-auto">
              <code v-for="item in batchResult" :key="item.id" class="rounded-md bg-muted px-2 py-1 text-xs text-foreground">{{ item.code }}</code>
            </div>
          </div>
          <DialogFooter class="gap-2">
            <Button type="button" variant="secondary" class="h-10" @click="closeBatchRedemptionModal">取消</Button>
            <Button type="submit" class="h-10" :disabled="batchRefreshing">{{ batchRefreshing ? '生成中...' : '立即生成' }}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>

    <!-- 兑换码详情（右侧抽屉）：完整展示该兑换码的全部信息与已兑换用户列表 -->
    <Sheet :open="!!selectedRedemptionDetail" @update:open="(value) => !value && closeRedemptionDetail()">
      <SheetContent side="right" class="w-full overflow-y-auto p-5 sm:max-w-md">
        <SheetHeader class="gap-0.5 pb-2">
          <SheetDescription class="text-[13px] font-bold tracking-widest text-primary">兑换码详情</SheetDescription>
          <SheetTitle class="break-all font-display text-xl">{{ selectedRedemptionDetail?.code }}</SheetTitle>
        </SheetHeader>
        <div class="grid gap-4">
          <div class="grid gap-1.5 rounded-xl border bg-muted/50 p-3.5 text-sm">
            <span class="flex flex-wrap items-baseline justify-between gap-x-3">完整兑换码<strong class="break-all text-foreground">{{ selectedRedemptionDetail?.code }}</strong></span>
            <span class="flex flex-wrap items-baseline justify-between gap-x-3 text-muted-foreground">兑换面额<strong class="text-foreground tabular-nums">¥{{ Number(selectedRedemptionDetail?.amount || 0).toFixed(2) }}</strong></span>
            <span class="flex flex-wrap items-baseline justify-between gap-x-3 text-muted-foreground">已兑换次数<strong class="text-foreground tabular-nums">{{ selectedRedemptionDetail?.used_count }} / {{ selectedRedemptionDetail?.usable_count }}</strong></span>
            <span class="flex flex-wrap items-baseline justify-between gap-x-3 text-muted-foreground">生成时间<strong class="text-foreground">{{ selectedRedemptionDetail?.created_at ? formatDateTime(selectedRedemptionDetail.created_at) : '-' }}</strong></span>
            <!-- 【新增功能】有效期类型：date=管理员指定到期日期（此时天数列显示 —），days=按有效天数。 -->
            <span class="flex flex-wrap items-baseline justify-between gap-x-3 text-muted-foreground">有效期类型<strong class="text-foreground">{{ selectedRedemptionDetail?.expiry_mode === 'date' ? '指定到期日期' : '按有效天数' }}</strong></span>
            <span class="flex flex-wrap items-baseline justify-between gap-x-3 text-muted-foreground">有效天数<strong class="text-foreground">{{ selectedRedemptionDetail ? redemptionDetailValidDays(selectedRedemptionDetail) : '-' }}</strong></span>
            <span class="flex flex-wrap items-baseline justify-between gap-x-3 text-muted-foreground">精确到期<strong class="text-foreground">{{ selectedRedemptionDetail?.expires_at ? formatDateTime(selectedRedemptionDetail.expires_at) : '永久有效' }}</strong></span>
            <span class="flex flex-wrap items-baseline justify-between gap-x-3 text-muted-foreground">单用户使用上限<strong class="text-foreground">{{ selectedRedemptionDetail && selectedRedemptionDetail.per_user_max_times > 0 ? `每人最多 ${selectedRedemptionDetail.per_user_max_times} 次` : '不限制' }}</strong></span>
            <span class="flex flex-wrap items-baseline justify-between gap-x-3 text-muted-foreground">使用状态<strong class="text-foreground">{{ selectedRedemptionDetail ? redemptionStatusLabel(selectedRedemptionDetail.status) : '-' }}</strong></span>
            <span class="flex flex-wrap items-baseline justify-between gap-x-3 text-muted-foreground">累计可兑金额<strong class="text-foreground tabular-nums">¥{{ Number(selectedRedemptionDetail?.total_amount || 0).toFixed(2) }}</strong></span>
          </div>

          <h3 class="text-sm font-bold text-foreground">已兑换用户</h3>
          <div v-if="redemptionDetailLoading" class="rounded-lg border border-dashed bg-muted/40 px-4 py-6 text-center text-sm text-muted-foreground">加载中...</div>
          <div v-else-if="redemptionLogs.length === 0" class="rounded-lg border border-dashed bg-muted/40 px-4 py-6 text-center text-sm text-muted-foreground">暂无兑换记录</div>
          <div v-else class="grid gap-2">
            <div v-for="log in redemptionLogs" :key="log.id" class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 rounded-lg border bg-card px-3 py-2 text-sm">
              <div class="grid min-w-0 gap-0.5">
                <strong class="break-all text-foreground">{{ log.real_name || log.username || log.user_id || '未知用户' }}</strong>
                <span class="text-xs text-muted-foreground">{{ formatDateTime(log.created_at) }}</span>
              </div>
              <strong class="font-display text-primary tabular-nums">¥{{ Number(log.amount).toFixed(2) }}</strong>
            </div>
          </div>

          <Button class="h-10" @click="closeRedemptionDetail">关闭</Button>
        </div>
      </SheetContent>
    </Sheet>

    <!-- 订单详情弹窗：点「详情」弹出，内容区内部滚动，字段用紧凑栅格排版 -->
    <Dialog :open="!!selectedOrderDetail" @update:open="(value) => !value && closeOrderDetail()">
      <DialogContent class="max-h-[85dvh] overflow-y-auto max-sm:max-w-[calc(100vw-1.5rem)] sm:max-w-3xl">
        <DialogHeader>
          <DialogDescription class="text-[13px] font-bold tracking-widest text-primary">订单详情</DialogDescription>
          <DialogTitle class="break-all font-display text-xl">{{ selectedOrderDetail?.order.id }}</DialogTitle>
        </DialogHeader>
        <div v-if="selectedOrderDetail" class="grid gap-4">
          <div class="grid gap-x-6 gap-y-1.5 rounded-lg border bg-muted/40 p-3.5 text-sm sm:grid-cols-2 xl:grid-cols-3">
            <span class="text-muted-foreground">订单号：<strong class="break-all text-foreground">{{ selectedOrderDetail.order.id }}</strong></span>
            <span class="text-muted-foreground">打印人：<strong class="text-foreground">{{ selectedOrderDetail.order.contact_name || '-' }}</strong></span>
            <span class="text-muted-foreground">联系电话：<strong class="text-foreground">{{ selectedOrderDetail.order.contact_phone || '-' }}</strong></span>
            <span class="text-muted-foreground">金额：<strong class="text-foreground tabular-nums">¥{{ Number(selectedOrderDetail.order.total_amount || 0).toFixed(2) }}</strong></span>
            <span class="text-muted-foreground">原价：<strong class="text-foreground tabular-nums">¥{{ Number(selectedOrderDetail.order.base_amount || selectedOrderDetail.order.total_amount || 0).toFixed(2) }}</strong></span>
            <span class="text-muted-foreground">优惠：<strong class="text-foreground tabular-nums">¥{{ Number(selectedOrderDetail.order.discount_amount || 0).toFixed(2) }}{{ orderDiscountLabel(selectedOrderDetail.order) ? ` · ${orderDiscountLabel(selectedOrderDetail.order)}` : '' }}</strong></span>
            <span class="text-muted-foreground">计费张数：<strong class="text-foreground">{{ selectedOrderDetail.order.sheet_count || 0 }} 张</strong></span>
            <span class="text-muted-foreground">支付方式：<strong class="text-foreground">{{ formatPaymentMethod(selectedOrderDetail.order.payment_method) }}</strong></span>
            <span class="text-muted-foreground">支付状态：<strong class="text-foreground">{{ formatOrderPaymentStatus(selectedOrderDetail.order) }}</strong></span>
            <span class="text-muted-foreground">打印状态：<strong class="text-foreground">{{ formatPrintStatus(selectedOrderDetail.order.status) }}</strong></span>
            <span class="text-muted-foreground">支付时间：<strong class="text-foreground">{{ selectedOrderDetail.order.payment_paid_at || selectedOrderDetail.order.paid_at || '-' }}</strong></span>
            <span class="text-muted-foreground">打印时间：<strong class="text-foreground">{{ selectedOrderDetail.order.printed_at || '-' }}</strong></span>
            <span class="text-muted-foreground">份数：<strong class="text-foreground">{{ selectedOrderDetail.order.copies || 1 }}</strong></span>
            <span class="text-muted-foreground">双面：<strong class="text-foreground">{{ selectedOrderDetail.order.is_double_sided ? '含双面文档（见下方各文件）' : '全部单面' }}</strong></span>
            <span class="text-muted-foreground">打印机：<strong class="text-foreground">{{ selectedOrderDetail.order.printer_name || '默认打印机' }}</strong></span>
            <span class="text-muted-foreground">用户：<strong class="text-foreground">{{ selectedOrderDetail.user.username || '访客/已删除用户' }}</strong></span>
            <span class="text-muted-foreground">创建：<strong class="text-foreground">{{ selectedOrderDetail.order.created_at || '-' }}</strong></span>
            <span class="text-muted-foreground">易支付交易号：<strong class="text-foreground">{{ selectedOrderDetail.order.epay_trade_no || '-' }}</strong></span>
          </div>

          <h3 class="font-display text-base font-bold">上传文件</h3>
          <div class="grid gap-2">
            <div v-for="file in selectedOrderDetail.files" :key="file.id" class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border bg-card p-3 text-sm">
              <div class="grid min-w-0 gap-0.5">
                <strong class="break-all text-foreground">{{ file.original_name }}</strong>
                <span class="text-[13px] text-muted-foreground">{{ file.page_count || 0 }} 页 · {{ Number(file.file_size || 0).toFixed(2) }} MB · {{ file.uploaded_at || '-' }}</span>
                <small class="text-xs text-muted-foreground">{{ file.status || 'unknown' }} · {{ file.pdf_exists ? 'PDF 可预览' : 'PDF 缓存不存在' }}</small>
              </div>
              <div class="flex flex-wrap items-center gap-2">
                <Badge :class="file.is_safe ? 'border-transparent bg-success/10 text-success' : 'border-transparent bg-warning/15 text-warning'">{{ file.is_safe ? '安全' : '已拦截' }}</Badge>
                <Badge variant="outline">覆盖率 {{ Number(file.black_coverage || 0).toFixed(1) }}%</Badge>
                <Badge :class="file.is_double_sided ? 'border-transparent bg-success/10 text-success' : ''" :variant="file.is_double_sided ? undefined : 'secondary'">{{ file.is_double_sided ? '双面' : '单面' }}</Badge>
                <!-- 预览默认不加载：点「预览」才加载 iframe，再点（按钮变「收起预览」）即关闭 -->
                <Button variant="secondary" size="sm" class="h-8" :disabled="!file.preview_url" @click="previewOrderFile(file)">
                  <Eye />
                  {{ selectedOrderFile?.id === file.id ? '收起预览' : '预览' }}
                </Button>
              </div>
            </div>
            <div v-if="selectedOrderDetail.files.length === 0" class="rounded-lg border border-dashed bg-muted/40 px-4 py-6 text-center text-sm text-muted-foreground">该订单没有关联文件</div>
          </div>

          <div v-if="selectedOrderFile" class="grid gap-2">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <h3 class="break-all font-display text-sm font-bold">{{ selectedOrderFile.original_name }}</h3>
              <Button variant="secondary" size="sm" class="h-8" @click="selectedOrderFile = null">关闭预览</Button>
            </div>
            <iframe :src="selectedOrderFile.preview_url" title="订单文件预览" class="h-[55vh] min-h-80 w-full rounded-lg border bg-card"></iframe>
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" class="h-9" @click="closeOrderDetail">关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- 删除订单二次确认（AlertDialog）：deleteOrder / deleteUnpaidOrder / deleteAllUnpaidOrders 统一走这里 -->
    <AlertDialog :open="!!pendingConfirm" @update:open="(value) => !value && (pendingConfirm = null)">
      <AlertDialogContent class="max-sm:max-w-[calc(100vw-1.5rem)]">
        <AlertDialogHeader>
          <AlertDialogTitle>{{ pendingConfirm?.title }}</AlertDialogTitle>
          <AlertDialogDescription>{{ pendingConfirm?.description }}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction class="bg-destructive/10 text-destructive hover:bg-destructive/20 dark:bg-destructive/20 dark:hover:bg-destructive/30" @click="confirmPending">
            确认删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </SidebarProvider>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { toast } from 'vue-sonner'
import { Archive, CheckCircle, ClipboardList, CreditCard, DatabaseBackup, Download, ExternalLink, Eye, Gauge, Globe, House, Image as ImageIcon, MapPin, MoreHorizontal, Pencil, Plus, Power, Printer, RefreshCw, RotateCcw, Save, Search, Server, Settings, Target, Ticket, Trash2, TriangleAlert, UploadCloud, UserCog, X, XCircle, CircleCheck } from 'lucide-vue-next'
import { buildApiUrl, request } from '@/api/client'
import DailyStatsCard from '@/components/DailyStatsCard.vue'
import IcpFooter from '@/components/layout/IcpFooter.vue'
import ThemeToggle from '@/components/layout/ThemeToggle.vue'
import { useSiteStore } from '@/stores/site'
import { useAuthStore } from '@/stores/auth'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from '@/components/ui/sidebar'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const auth = useAuthStore()
// 站点设置保存后立即全局应用标题/favicon/备案条（前台与后台共用同一份配置）。
const site = useSiteStore()

const tabs = [
  { key: 'dashboard', label: '概览', icon: Gauge },
  { key: 'orders', label: '订单', icon: ClipboardList },
  { key: 'users', label: '用户', icon: UserCog },
  { key: 'settings', label: '配置', icon: Settings },
  { key: 'site', label: '站点设置', icon: Globe },
  { key: 'payment', label: '支付', icon: CreditCard },
  { key: 'redemptions', label: '兑换码', icon: Ticket },
  { key: 'backups', label: '备份', icon: DatabaseBackup },
  { key: 'printers', label: '打印机', icon: Printer }
]
const tab = ref('dashboard')
const currentTabLabel = computed(() => tabs.find((item) => item.key === tab.value)?.label || '后台')
// 手机端底部 Tab 栏：后台共 9 个 tab，窄屏底部放不下，因此常用 tab 常驻、其余收进「更多」面板。
// 桌面端不受影响，仍由侧边栏展示全部 tab；两端共用同一个 tab 状态与 loadTab()，
// 所以切换行为与点击侧边栏按钮完全一致（只改 tab ref，不涉及路由跳转）。
const MOBILE_PRIMARY_TAB_KEYS = ['dashboard', 'orders', 'users', 'settings']
const moreOpen = ref(false)
const primaryTabs = computed(() => tabs.filter((item) => MOBILE_PRIMARY_TAB_KEYS.includes(item.key)))
const moreTabs = computed(() => tabs.filter((item) => !MOBILE_PRIMARY_TAB_KEYS.includes(item.key)))
const moreCurrent = computed(() => moreTabs.value.find((item) => item.key === tab.value) || null)
const moreActive = computed(() => moreOpen.value || Boolean(moreCurrent.value))

function selectTab(key) {
  tab.value = key
  moreOpen.value = false
}

const dashboard = ref(null)
const orders = ref([])
const printQueue = ref({ total: 0, printing_count: 0, waiting_count: 0, items: [] })
const queueRefreshing = ref(false)
const selectedOrderDetail = ref(null)
const selectedOrderFile = ref(null)
const cacheCleanup = ref({ start_at: '', end_at: '', include_order_files: false })
const cacheCleanupResult = ref(null)
const users = ref([])
const settings = ref({})
// 站点设置：表单回显 + 分组保存；siteFaviconPreviewUrl 是当前生效图标（用于预览与「已生效」提示）。
const siteSettings = ref(null)
const siteSettingsForm = ref({ site_title: '', site_favicon_mode: 'none', site_favicon_url: '', site_icp_number: '', login_lock_threshold: 5, login_lock_minutes: 15 })
const siteFaviconPreviewUrl = ref('')
const siteFaviconUploading = ref(false)
const siteFaviconInput = ref(null)
const siteFaviconModes = [
  { value: 'upload', label: '上传图标' },
  { value: 'url', label: '图标 URL' },
  { value: 'none', label: '不设置' }
]
const paymentSettings = ref({})
const paymentTest = ref({ payment_method: 'alipay', amount: 0.01 })
const paymentTestResult = ref(null)
const printers = ref([])
const printerDrivers = ref([{ id: 'everywhere', label: 'IPP Everywhere / AirPrint / Mopria', recommended: true }])
const printerDriverAdvice = ref(null)
const ppdUploadInput = ref(null)
const printerSystem = ref({ connected: false, pycups_available: false, diagnostics: [] })
const selectedPrinterInfo = ref(null)
const selectedPrinterJobs = ref([])
const backups = ref([])
const backupPolicy = ref({ enabled: false, frequency: 'daily', time: '03:00', weekday: 0, retention_count: 7, last_run_at: '' })
const backupCreate = ref({ archive_format: 'zip' })
const backupBusy = ref(false)
const restoreBusy = ref(false)
const restoreDragging = ref(false)
const restoreFile = ref(null)
const restoreInfo = ref(null)
// 兑换码管理
const redemptions = ref([])
const redemptionsTotal = ref(0)
const redemptionsHasMore = ref(false)
const redemptionLoadingMore = ref(false)
const redemptionSearch = ref('')
const showAddRedemptionModal = ref(false)
const showBatchRedemptionModal = ref(false)
const redemptionSaving = ref(false)
const batchRefreshing = ref(false)
// per_user_limit_enabled = 弹窗开关；per_user_max_times = 开关旁的数字输入框（正整数）。
// 【新增功能】expiry_mode = 有效期方式（'days' 按天数 / 'date' 指定到期日期，二选一）；
// expire_date = 日期控件值（原生 YYYY-MM-DD），仅在 'date' 模式提交给后端。
const redemptionForm = ref({ code: '', amount: null, usable_count: 1, valid_days: 0, expiry_mode: 'days', expire_date: '', per_user_limit_enabled: false, per_user_max_times: 1 })
// 分组底部那行小字里的 N：开关关闭时显示占位 N（不限制），开启时显示实际填写的最大次数。
// 纯展示计算，不参与校验与提交（提交仍由 saveAddRedemption() 决定，开关关闭发 0）。
const perUserMaxTimesHint = computed(() => {
  if (!redemptionForm.value.per_user_limit_enabled) return 'N'
  const times = Math.floor(Number(redemptionForm.value.per_user_max_times))
  return Number.isFinite(times) && times >= 1 ? String(times) : 'N'
})
const batchRedemptionForm = ref({ count: 10, amount: null, usable_count: 1, valid_days: 0, expiry_mode: 'days', expire_date: '' })
// 【新增功能】有效期提示行（两个弹窗共用一套文案）：日期模式显示到期时刻，天数模式说明 0=永久。
function redemptionExpiryHintOf(form) {
  if (form.expiry_mode === 'date') {
    return form.expire_date ? `到期时间：${form.expire_date} 23:59:59` : '请选择到期日期'
  }
  const days = Math.floor(Number(form.valid_days || 0))
  return days > 0 ? `自创建起 ${days} 天后到期` : '填 0 表示永久有效'
}
const redemptionExpiryHint = computed(() => redemptionExpiryHintOf(redemptionForm.value))
const batchRedemptionExpiryHint = computed(() => redemptionExpiryHintOf(batchRedemptionForm.value))
// 列表「有效期」列：指定到期日期只显示到期时刻；按天数额外标明天数（永久有效两者一致）。
function redemptionExpiryText(code) {
  if (!code.expires_at) return '永久有效'
  const deadline = `截止 ${formatDateTime(code.expires_at)}`
  if (code.expiry_mode === 'date') return deadline
  const days = Math.floor(Number(code.valid_days || 0))
  return days > 0 ? `${days} 天 · ${deadline}` : deadline
}
// 详情抽屉「有效天数」：指定到期日期模式下天数无意义（后端已写 0），显示占位符避免误读为永久有效。
function redemptionDetailValidDays(code) {
  if (code.expiry_mode === 'date') return '—（按到期日期）'
  const days = Number(code.valid_days || 0)
  return days > 0 ? `${days} 天` : '永久有效'
}
const batchResult = ref([])
const selectedRedemptionDetail = ref(null)
const redemptionDetailLoading = ref(false)
const redemptionLogs = ref([])
const showAddPrinterModal = ref(false)
const feedback = ref('')
const feedbackType = ref('success')
const standardPricingKeys = ['single_price', 'duplex_price']
const coveragePricingKeys = ['coverage_single_base_price', 'coverage_duplex_base_price']
const commonSettingKeys = ['min_balance', 'safety_coverage_limit', 'max_file_size_mb', 'max_pages']
const defaultBulkDiscountRules = [
  { min_sheets: 10, discount_percent: 95 },
  { min_sheets: 100, discount_percent: 90 },
  { min_sheets: 200, discount_percent: 80 }
]
const settingLabels = {
  single_price: '标准单面价格',
  duplex_price: '标准双面价格',
  coverage_single_base_price: '覆盖率单面基础价',
  coverage_duplex_base_price: '覆盖率双面基础价',
  min_balance: '最低余额',
  safety_coverage_limit: '覆盖率阈值',
  max_file_size_mb: '文件大小限制',
  max_pages: '最大页数',
  cups_server: 'CUPS 服务器地址',
  cups_user: 'CUPS 用户名',
  cups_password: 'CUPS 密码'
}
const emptyPrinter = { editingName: '', name: '', uri: '', driver: 'everywhere', location: '', description: '', is_default: false, is_enabled: true, accepting_jobs: true, is_support_color: false, is_support_auto_duplex: true }
const printerForm = ref({ ...emptyPrinter })
const emptyUser = { id: '', username: '', password: '', email: '', phone: '', balance: 0, is_admin: false, is_active: true }
const userForm = ref({ ...emptyUser })
const balanceDeltas = ref({})
const balanceTargets = ref({})
const visiblePricingKeys = computed(() => settings.value.pricing_mode === 'coverage_tiered' ? coveragePricingKeys : standardPricingKeys)
const unpaidOrdersCount = computed(() => orders.value.filter((order) => canDeleteUnpaid(order)).length)
const weekdayLabels = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const selectedPrinterDriver = computed(() => printerDrivers.value.find((driver) => driver.id === printerForm.value.driver))

// 概览指标卡（展示顺序与旧版一致）
const dashboardMetrics = computed(() => [
  { label: '订单数', value: dashboard.value?.totals.orders_count || 0 },
  { label: '收入', value: `¥${Number(dashboard.value?.totals.revenue || 0).toFixed(2)}` },
  { label: '待支付', value: dashboard.value?.totals.pending_orders || 0 },
  { label: '打印失败', value: dashboard.value?.totals.failed_prints || 0 },
  { label: '正在打印', value: dashboard.value?.totals.printing_count || 0 },
  { label: '排队中', value: dashboard.value?.totals.queue_count || 0 }
])

// 支付配置表单字段
const paymentFields = [
  { key: 'epay_gateway', label: '网关地址', type: 'text' },
  { key: 'epay_pid', label: '商户 ID', type: 'text' },
  { key: 'epay_key', label: '商户密钥', type: 'password' },
  { key: 'public_base_url', label: '公网回调地址', type: 'text' },
  { key: 'frontend_base_url', label: '前端返回地址', type: 'text' }
]

// 打印机顶部状态卡
const printerStatCards = computed(() => [
  { label: 'CUPS 连接', value: printerSystem.value.connected ? '已连接' : '未连接', icon: Server, iconClass: printerSystem.value.connected ? '' : 'text-destructive' },
  { label: '打印机数量', value: printerSystem.value.printer_count || 0, icon: Printer },
  { label: '默认打印机', value: printerSystem.value.default_printer || '未设置', icon: Target }
])

// 打印机实时状态卡
const printerInfoStats = computed(() => selectedPrinterInfo.value ? [
  { label: '状态', value: selectedPrinterInfo.value.state_text || selectedPrinterInfo.value.state },
  { label: '队列任务', value: selectedPrinterInfo.value.queued_jobs || 0 },
  { label: '持续时间', value: `${selectedPrinterInfo.value.state_duration_seconds || 0} 秒` },
  { label: '固件', value: selectedPrinterInfo.value.firmware_version || '-' }
] : [])

// 备份摘要卡
const backupSummary = [
  { title: '数据库', desc: '订单、用户、支付、配置、打印机' },
  { title: '上传文件', desc: '原始文件、转换 PDF、预览缓存' },
  { title: '配置与日志', desc: 'compose/env 配置和 logs 目录' }
]

// 状态语义 → Badge 配色（success/warning/neutral 三类，全部走 CSS 变量）
function statusBadgeClass(kind) {
  if (kind === 'success') return 'border-transparent bg-success/10 text-success'
  if (kind === 'warning') return 'border-transparent bg-warning/15 text-warning'
  return 'border-transparent bg-accent text-accent-foreground'
}

function printerStateClass(state) {
  if (state === 'idle') return 'border-transparent bg-success/10 text-success'
  if (state === 'processing') return 'border-transparent bg-accent text-accent-foreground'
  if (state === 'stopped') return 'border-transparent bg-warning/15 text-warning'
  return ''
}

function showFeedback(message, type = 'success') {
  feedback.value = message
  feedbackType.value = type
}

// 删除订单的二次确认（AlertDialog）：pendingConfirm = { title, description, action }，
// 确认按钮执行 action（真正的删除请求逻辑保持不变）。
const pendingConfirm = ref(null)

function requestConfirm(title, description, action) {
  pendingConfirm.value = { title, description, action }
}

function confirmPending() {
  const action = pendingConfirm.value?.action
  pendingConfirm.value = null
  if (typeof action === 'function') action()
}

async function runAction(action, successMessage) {
  try {
    await action()
    showFeedback(successMessage)
  } catch (error) {
    showFeedback(error.message, 'warning')
  }
}

async function loadTab() {
  feedback.value = ''
  if (tab.value === 'dashboard') dashboard.value = await request('/api/admin/dashboard')
  if (tab.value === 'orders') {
    orders.value = await request('/api/admin/orders')
    printQueue.value = await request('/api/admin/print-queue')
  }
  if (tab.value === 'users') {
    users.value = await request('/api/admin/users')
    balanceTargets.value = Object.fromEntries(users.value.map((user) => [user.id, Number(user.balance || 0)]))
  }
  if (tab.value === 'settings') settings.value = normalizeSettings(await request('/api/admin/settings'))
  if (tab.value === 'site') applySiteSettingsData(await request('/api/admin/site-settings'))
  if (tab.value === 'payment') paymentSettings.value = await request('/api/admin/payment-settings')
  if (tab.value === 'backups') {
    const result = await request('/api/admin/backups')
    backups.value = result.backups || []
    backupPolicy.value = { ...backupPolicy.value, ...(result.policy || {}) }
  }
  if (tab.value === 'redemptions') {
    await loadRedemptions()
  }
  if (tab.value === 'printers') {
    await loadPrinterPanel()
  }
}

// 兑换码管理：首次加载（重置搜索与分页）。
async function loadRedemptions() {
  const params = new URLSearchParams({ limit: 20, offset: 0 })
  if (redemptionSearch.value) params.set('search', redemptionSearch.value)
  const data = await request(`/api/admin/redemptions?${params.toString()}`)
  redemptions.value = data.items || []
  redemptionsTotal.value = data.total || 0
  redemptionsHasMore.value = Boolean(data.has_more)
  redemptionLoadingMore.value = false
}

async function loadMoreRedemptions() {
  if (redemptionLoadingMore.value || !redemptionsHasMore.value) return
  redemptionLoadingMore.value = true
  try {
    const params = new URLSearchParams({ limit: 20, offset: redemptions.value.length })
    if (redemptionSearch.value) params.set('search', redemptionSearch.value)
    const data = await request(`/api/admin/redemptions?${params.toString()}`)
    const newItems = data.items || []
    const existingIds = new Set(redemptions.value.map((code) => code.id))
    redemptions.value = [...redemptions.value, ...newItems.filter((code) => !existingIds.has(code.id))]
    redemptionsTotal.value = data.total || 0
    redemptionsHasMore.value = Boolean(data.has_more)
  } finally {
    redemptionLoadingMore.value = false
  }
}

function openAddRedemption() {
  redemptionForm.value = { code: '', amount: null, usable_count: 1, valid_days: 0, expiry_mode: 'days', expire_date: '', per_user_limit_enabled: false, per_user_max_times: 1 }
  showAddRedemptionModal.value = true
}

function closeAddRedemptionModal() {
  showAddRedemptionModal.value = false
}

async function saveAddRedemption() {
  const amount = Number(redemptionForm.value.amount)
  const usable = Number(redemptionForm.value.usable_count || 1)
  const validDays = Number(redemptionForm.value.valid_days || 0)
  if (!Number.isFinite(amount) || amount <= 0) {
    showFeedback('请填写有效的兑换面额', 'warning')
    return
  }
  // 【新增功能】有效期两种互斥方式：日期模式必须选中日期，天数模式沿用原 0=永久逻辑。
  const expiryMode = redemptionForm.value.expiry_mode === 'date' ? 'date' : 'days'
  const expireDate = (redemptionForm.value.expire_date || '').trim()
  if (expiryMode === 'date' && !expireDate) {
    showFeedback('请选择到期日期', 'warning')
    return
  }
  // 【新增功能】每个用户最大兑换次数：开关关闭时提交 0（后端=关闭该限制，保持原有总次数逻辑）；
  // 开启时必须填正整数，否则拒绝提交，避免出现「开关打开但上限为 0」的歧义状态。
  const perUserLimitEnabled = Boolean(redemptionForm.value.per_user_limit_enabled)
  const perUserMaxTimes = Math.floor(Number(redemptionForm.value.per_user_max_times))
  if (perUserLimitEnabled && (!Number.isFinite(perUserMaxTimes) || perUserMaxTimes < 1)) {
    showFeedback('请输入每个用户最大兑换次数（正整数）', 'warning')
    return
  }
  redemptionSaving.value = true
  try {
    const payload = {
      // 兑换码允许留空：留空传空串，由后端自动生成随机兑换码（与弹窗提示一致）。
      code: redemptionForm.value.code || '',
      amount: Math.round(amount * 100) / 100,
      usable_count: Math.max(1, Math.floor(usable)),
      expiry_mode: expiryMode,
      // 日期模式提交 YYYY-MM-DD（后端归一化为当天 23:59:59）；天数模式置空，避免歧义。
      expire_date: expiryMode === 'date' ? expireDate : null,
      valid_days: expiryMode === 'date' ? 0 : Math.max(0, Math.floor(validDays)),
      per_user_max_times: perUserLimitEnabled ? perUserMaxTimes : 0
    }
    await request('/api/admin/redemptions', { method: 'POST', body: payload })
    closeAddRedemptionModal()
    showFeedback('兑换码已创建')
    await loadRedemptions()
  } catch (error) {
    showFeedback(error.message || '创建兑换码失败', 'warning')
  } finally {
    redemptionSaving.value = false
  }
}

function openBatchRedemption() {
  batchRedemptionForm.value = { count: 10, amount: null, usable_count: 1, valid_days: 0, expiry_mode: 'days', expire_date: '' }
  batchResult.value = []
  showBatchRedemptionModal.value = true
}

function closeBatchRedemptionModal() {
  showBatchRedemptionModal.value = false
}

async function saveBatchRedemption() {
  const count = Number(batchRedemptionForm.value.count || 10)
  const amount = Number(batchRedemptionForm.value.amount)
  const usable = Number(batchRedemptionForm.value.usable_count || 1)
  const validDays = Number(batchRedemptionForm.value.valid_days || 0)
  if (!Number.isFinite(amount) || amount <= 0) {
    showFeedback('请填写有效的单张面额', 'warning')
    return
  }
  // 【新增功能】批量生成的有效期同样二选一，校验与手动新增保持一致。
  const expiryMode = batchRedemptionForm.value.expiry_mode === 'date' ? 'date' : 'days'
  const expireDate = (batchRedemptionForm.value.expire_date || '').trim()
  if (expiryMode === 'date' && !expireDate) {
    showFeedback('请选择到期日期', 'warning')
    return
  }
  batchRefreshing.value = true
  try {
    const payload = {
      count: Math.min(1000, Math.max(1, Math.floor(count))),
      amount: Math.round(amount * 100) / 100,
      usable_count: Math.max(1, Math.floor(usable)),
      expiry_mode: expiryMode,
      expire_date: expiryMode === 'date' ? expireDate : null,
      valid_days: expiryMode === 'date' ? 0 : Math.max(0, Math.floor(validDays))
    }
    const data = await request('/api/admin/redemptions/batch', { method: 'POST', body: payload })
    batchResult.value = data.codes || []
  } catch (error) {
    showFeedback(error.message || '批量生成失败', 'warning')
  } finally {
    batchRefreshing.value = false
  }
}

async function copyBatchResult() {
  const text = batchResult.value.map((item) => item.code).join('\n')
  try {
    await navigator.clipboard.writeText(text)
    toast.success('兑换码已复制到剪贴板')
  } catch {
    // 剪贴板 API 被禁用时回退到临时 textarea 选中复制。
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    toast.success('兑换码已复制到剪贴板')
  }
}

// 打开「详情」二级界面：先展示列表项已有的全部字段，再异步补齐该兑换码的已兑换用户列表。
async function openRedemptionDetail(code) {
  selectedRedemptionDetail.value = code
  redemptionLogs.value = []
  redemptionDetailLoading.value = true
  try {
    const data = await request(`/api/admin/redemptions/${code.id}/logs`)
    redemptionLogs.value = data.logs || []
  } catch (error) {
    showFeedback(error.message || '加载兑换记录失败', 'warning')
  } finally {
    redemptionDetailLoading.value = false
  }
}

function closeRedemptionDetail() {
  selectedRedemptionDetail.value = null
  redemptionDetailLoading.value = false
  redemptionLogs.value = []
}

async function deleteRedemption(code) {
  if (!confirm(`确定删除兑换码 ${code.code} 吗？删除后不可恢复。`)) return
  try {
    await request(`/api/admin/redemptions/${code.id}`, { method: 'DELETE' })
    showFeedback('兑换码已删除')
    await loadRedemptions()
  } catch (error) {
    showFeedback(error.message || '删除兑换码失败', 'warning')
  }
}

function redemptionStatusLabel(status) {
  return { unused: '未使用', used: '已使用', expired: '已过期' }[status] || status || '未知'
}

function redemptionStatusClass(status) {
  return { unused: 'success', used: 'warning', expired: 'info' }[status] || 'info'
}

async function loadPrinterPanel() {
  printerSystem.value = await request('/api/admin/printer-system')
  try {
    const printerResult = await request('/api/admin/printers')
    printers.value = printerResult
  } catch (error) {
    printers.value = []
    showFeedback(error.message, 'warning')
  }
  fetchPrinterDrivers()
}

async function fetchPrinterDrivers() {
  try {
    const driverResult = await request('/api/admin/printer-drivers?limit=50')
    printerDrivers.value = normalizePrinterDrivers(driverResult.drivers || [])
    printerDriverAdvice.value = driverResult.recommendation?.install_hint || null
  } catch (error) {
    printerDrivers.value = []
  }
}

async function createBackup() {
  backupBusy.value = true
  try {
    await runAction(async () => {
      await request('/api/admin/backups', { method: 'POST', body: backupCreate.value })
      await loadTab()
    }, '备份已创建')
  } finally {
    backupBusy.value = false
  }
}

async function saveBackupPolicy() {
  await runAction(async () => {
    backupPolicy.value = await request('/api/admin/backups/policy', { method: 'PUT', body: backupPolicy.value })
    await loadTab()
  }, '自动备份策略已保存')
}

function downloadBackup(backup) {
  window.open(buildApiUrl(backup.download_url), '_blank', 'noopener,noreferrer')
}

async function deleteBackup(backup) {
  if (!window.confirm(`确认删除备份 ${backup.filename}？`)) return
  await runAction(async () => {
    await request(`/api/admin/backups/${encodeURIComponent(backup.filename)}`, { method: 'DELETE' })
    await loadTab()
  }, '备份已删除')
}

async function chooseRestoreFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (file) await inspectRestoreFile(file)
}

async function dropRestoreFile(event) {
  restoreDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) await inspectRestoreFile(file)
}

async function inspectRestoreFile(file) {
  restoreFile.value = file
  restoreInfo.value = null
  const body = new FormData()
  body.append('file', file)
  await runAction(async () => {
    restoreInfo.value = await request('/api/admin/backups/inspect', { method: 'POST', body })
  }, '备份校验通过')
}

async function restoreBackup() {
  if (!restoreFile.value || !restoreInfo.value) return
  if (!window.confirm(`确认用 ${restoreInfo.value.filename} 覆盖当前系统数据？恢复会替换数据库、上传文件、日志和配置。`)) return
  restoreBusy.value = true
  const body = new FormData()
  body.append('file', restoreFile.value)
  try {
    await runAction(async () => {
      await request('/api/admin/backups/restore', { method: 'POST', body })
      showFeedback('恢复完成，页面即将刷新')
      window.setTimeout(() => window.location.reload(), 900)
    }, '恢复完成')
  } finally {
    restoreBusy.value = false
  }
}

async function completeOrder(id) {
  await runAction(async () => {
    await request(`/api/admin/orders/${id}/mark-complete`, { method: 'POST' })
    await loadTab()
  }, '订单已标记完成')
}

async function refreshPrintStatus() {
  queueRefreshing.value = true
  try {
    const result = await request('/api/admin/orders/refresh-print-status', { method: 'POST' })
    if (result.queue) printQueue.value = result.queue
    orders.value = await request('/api/admin/orders')
    showFeedback(`已刷新打印状态，更新了 ${result.updated || 0} 个订单`)
  } catch (error) {
    showFeedback(error.message, 'warning')
  } finally {
    queueRefreshing.value = false
  }
}

async function deleteOrder(order) {
  requestConfirm(`确认删除订单 ${order.id}？`, '订单详情会删除，该订单独占的本地源文件/PDF缓存也会删除；被其他订单共用的文件会保留。', async () => {
    await runAction(async () => {
      await request(`/api/admin/orders/${order.id}`, { method: 'DELETE' })
      if (selectedOrderDetail.value?.order?.id === order.id) closeOrderDetail()
      await loadTab()
    }, '订单已删除')
  })
}

async function deleteUnpaidOrder(order) {
  requestConfirm(`确认删除未支付订单 ${order.id}？`, '订单记录和该订单独占的文件缓存会删除。', async () => {
    await runAction(async () => {
      await request(`/api/admin/orders/${order.id}/unpaid`, { method: 'DELETE' })
      if (selectedOrderDetail.value?.order?.id === order.id) closeOrderDetail()
      await loadTab()
    }, '未支付订单已删除')
  })
}

async function deleteAllUnpaidOrders() {
  const count = unpaidOrdersCount.value
  if (!count) return
  requestConfirm(`确认删除全部 ${count} 个未支付订单？`, '订单记录和这些订单独占的文件缓存会删除。', async () => {
    await runAction(async () => {
      const result = await request('/api/admin/orders/unpaid/bulk', { method: 'DELETE' })
      if (result.deleted_order_ids?.includes(selectedOrderDetail.value?.order?.id)) closeOrderDetail()
      await loadTab()
    }, `已删除 ${count} 个未支付订单`)
  })
}

async function loadOrderDetail(id) {
  await runAction(async () => {
    selectedOrderDetail.value = await request(`/api/admin/orders/${id}/detail`)
    // 默认不加载预览：只展示文件列表（文件名/页数/大小/时间/状态标签），
    // 点「预览」按钮后才加载 iframe；每次打开弹窗都是未预览状态，不残留上次的选择。
    selectedOrderFile.value = null
  }, '订单详情已加载')
}

function closeOrderDetail() {
  selectedOrderDetail.value = null
  selectedOrderFile.value = null
}

function previewOrderFile(file) {
  // 点「预览」加载并展示；再点同一文件的按钮（或点预览区的「关闭预览」）即收起，iframe 卸载。
  selectedOrderFile.value = selectedOrderFile.value?.id === file.id ? null : file
}

function cacheCleanupPayload(dryRun) {
  return {
    start_at: cacheCleanup.value.start_at || null,
    end_at: cacheCleanup.value.end_at || null,
    include_order_files: Boolean(cacheCleanup.value.include_order_files),
    dry_run: dryRun
  }
}

async function previewFileCacheCleanup() {
  await runAction(async () => {
    cacheCleanupResult.value = await request('/api/admin/file-cache/cleanup', { method: 'POST', body: cacheCleanupPayload(true) })
  }, '缓存统计完成')
}

async function cleanupFileCache() {
  const includeOrderFiles = cacheCleanup.value.include_order_files
  const message = includeOrderFiles ? '确认清理所选时段内的缓存？包含订单关联文件后，相关订单将无法继续预览这些文件。' : '确认清理所选时段内未关联订单的文件缓存？'
  if (!window.confirm(message)) return
  await runAction(async () => {
    cacheCleanupResult.value = await request('/api/admin/file-cache/cleanup', { method: 'POST', body: cacheCleanupPayload(false) })
    if (selectedOrderDetail.value) {
      const orderId = selectedOrderDetail.value.order.id
      selectedOrderDetail.value = await request(`/api/admin/orders/${orderId}/detail`)
      // 清理后缓存可能已被删除，重置预览状态（保持「默认未预览」，需要时重新点「预览」）。
      selectedOrderFile.value = null
    }
  }, '缓存清理完成')
}

function resetUserForm() {
  userForm.value = { ...emptyUser }
}

function fillUser(user) {
  userForm.value = {
    id: user.id,
    username: user.username,
    password: '',
    email: user.email || '',
    phone: user.phone || '',
    balance: Number(user.balance || 0),
    is_admin: Boolean(user.is_admin),
    is_active: Boolean(user.is_active)
  }
}

async function saveUser() {
  await runAction(async () => {
    const body = { ...userForm.value }
    const userId = body.id
    delete body.id
    if (userId) {
      const balance = Number(body.balance)
      if (!Number.isFinite(balance) || balance < 0) throw new Error('请输入有效余额')
      delete body.balance
      if (!body.password) delete body.password
      await request(`/api/admin/users/${userId}`, { method: 'PUT', body })
      await request(`/api/admin/users/${userId}/balance`, { method: 'PUT', body: { balance } })
    } else {
      await request('/api/admin/users', { method: 'POST', body })
    }
    resetUserForm()
    await loadTab()
  }, userForm.value.id ? '用户已更新' : '用户已创建')
}

async function adjustBalance(userId) {
  await runAction(async () => {
    const amount = Number(balanceDeltas.value[userId] || 0)
    if (!amount) throw new Error('请输入余额增减金额')
    await request(`/api/admin/users/${userId}/balance`, { method: 'POST', body: { amount } })
    balanceDeltas.value[userId] = ''
    await loadTab()
  }, '用户余额已更新')
}

async function setBalance(userId) {
  await runAction(async () => {
    const balance = Number(balanceTargets.value[userId])
    if (!Number.isFinite(balance) || balance < 0) throw new Error('请输入有效余额')
    await request(`/api/admin/users/${userId}/balance`, { method: 'PUT', body: { balance } })
    await loadTab()
  }, '用户余额已修改')
}

async function toggleUser(user) {
  await runAction(async () => {
    await request(`/api/admin/users/${user.id}/toggle`, { method: 'POST' })
    await loadTab()
  }, user.is_active ? '账户已封禁' : '账户已解封')
}

const adminUserCount = computed(() => users.value.filter((user) => user.is_admin).length)

function userDeleteBlockReason(user) {
  if (auth.user && user.id === auth.user.id) return '不能删除当前登录管理员'
  if (user.is_admin && adminUserCount.value <= 1) return '至少保留一个管理员'
  return ''
}

async function deleteUser(user) {
  const blockReason = userDeleteBlockReason(user)
  if (blockReason) {
    showFeedback(blockReason, 'warning')
    return
  }
  if (!window.confirm(`确认删除用户 ${user.username}？历史订单会保留但不再关联该用户。`)) return
  await runAction(async () => {
    await request(`/api/admin/users/${user.id}`, { method: 'DELETE' })
    delete balanceDeltas.value[user.id]
    delete balanceTargets.value[user.id]
    await loadTab()
  }, '用户已删除')
}

function parseJsonSetting(value, fallback) {
  if (Array.isArray(value)) return value
  if (typeof value !== 'string' || !value) return fallback
  try {
    const parsed = JSON.parse(value)
    return Array.isArray(parsed) ? parsed : fallback
  } catch {
    return fallback
  }
}

function discountToPercent(value, fallback = 100) {
  const discount = Number(value)
  if (!Number.isFinite(discount) || discount <= 0) return fallback
  return discount <= 1 ? Math.round(discount * 100) : Math.round(discount)
}

function normalizeBoolean(value) {
  if (typeof value === 'boolean') return value
  return ['1', 'true', 'yes', 'on'].includes(String(value || '').toLowerCase())
}

function normalizeSettings(rawSettings) {
  const next = { ...rawSettings }
  const parsedRules = parseJsonSetting(next.bulk_discount_rules, defaultBulkDiscountRules)
  next.bulk_discount_enabled = next.bulk_discount_enabled === undefined ? true : normalizeBoolean(next.bulk_discount_enabled)
  next.bulk_discount_rules = parsedRules.map((rule) => ({
    min_sheets: Number(rule.min_sheets || 0),
    discount_percent: discountToPercent(rule.discount, 95)
  })).filter((rule) => rule.min_sheets > 0)
  next.daily_limited_offer_enabled = normalizeBoolean(next.daily_limited_offer_enabled)
  next.daily_limited_offer_all_day = normalizeBoolean(next.daily_limited_offer_all_day)
  next.daily_limited_offer_free = normalizeBoolean(next.daily_limited_offer_free)
  next.daily_limited_offer_start_time = next.daily_limited_offer_start_time || ''
  next.daily_limited_offer_end_time = next.daily_limited_offer_end_time || ''
  next.daily_limited_offer_sheet_quota = Number(next.daily_limited_offer_sheet_quota || 0)
  next.daily_limited_offer_discount_percent = discountToPercent(next.daily_limited_offer_discount, 100)
  return next
}

function addBulkDiscountRule() {
  if (!Array.isArray(settings.value.bulk_discount_rules)) settings.value.bulk_discount_rules = []
  settings.value.bulk_discount_rules.push({ min_sheets: 10, discount_percent: 95 })
}

function removeBulkDiscountRule(index) {
  settings.value.bulk_discount_rules.splice(index, 1)
}

function settingsPayload() {
  const body = { ...settings.value }
  body.bulk_discount_rules = (settings.value.bulk_discount_rules || [])
    .map((rule) => ({
      min_sheets: Number(rule.min_sheets || 0),
      discount: Number(rule.discount_percent || 0) / 100
    }))
    .filter((rule) => rule.min_sheets > 0 && rule.discount > 0 && rule.discount <= 1)
  body.daily_limited_offer_free = !!settings.value.daily_limited_offer_free
  body.daily_limited_offer_all_day = !!settings.value.daily_limited_offer_all_day
  // 勾选“全天生效”后忽略并清空开始/结束时间，避免残留旧的时间窗口值造成误解。
  if (body.daily_limited_offer_all_day) {
    body.daily_limited_offer_start_time = ''
    body.daily_limited_offer_end_time = ''
  }
  const discountPercent = Number(settings.value.daily_limited_offer_discount_percent || 0)
  // 完全免费时忽略折扣百分比，避免向后端发送不满足 gt=0/le=1 的折扣值。
  if (!body.daily_limited_offer_free && discountPercent > 0) {
    body.daily_limited_offer_discount = discountPercent / 100
  }
  delete body.daily_limited_offer_discount_percent
  return body
}

async function saveSettings(options = {}) {
  const reloadPrinters = options && options.reloadPrinters === true
  await runAction(async () => {
    await request('/api/admin/settings', { method: 'PUT', body: settingsPayload() })
    settings.value = normalizeSettings(settingsPayload())
    // 保存 CUPS 配置后重新拉取打印机列表，刷新默认打印机徽章与“设为默认”按钮状态。
    if (reloadPrinters) {
      await loadPrinterPanel()
    }
  }, '保存成功')
}

async function savePaymentSettings() {
  await runAction(async () => {
    await request('/api/admin/payment-settings', { method: 'PUT', body: paymentSettings.value })
    paymentSettings.value.epay_key = ''
    await loadTab()
  }, '保存成功')
}

// ===== 站点设置：回显 / 分组保存 / 图标上传 =====

function applySiteSettingsData(data) {
  siteSettings.value = data
  siteSettingsForm.value = {
    site_title: data.site_title || '',
    site_favicon_mode: data.site_favicon_mode || 'none',
    site_favicon_url: data.site_favicon_url || '',
    site_icp_number: data.site_icp_number || '',
    login_lock_threshold: Number(data.login_lock_threshold || 5),
    login_lock_minutes: Number(data.login_lock_minutes || 15)
  }
  siteFaviconPreviewUrl.value = data.site_favicon_effective_url || data.site_favicon_url || ''
}

// 分组保存：每组只提交自己的键（后端只更新传入的键），成功后把新配置即时应用到全站。
async function saveSiteSettingsGroup(group) {
  const form = siteSettingsForm.value
  const payloads = {
    lock: () => {
      const threshold = Math.floor(Number(form.login_lock_threshold))
      const minutes = Math.floor(Number(form.login_lock_minutes))
      if (!Number.isFinite(threshold) || threshold < 1) throw new Error('请填写有效的连续失败次数（正整数）')
      if (!Number.isFinite(minutes) || minutes < 1) throw new Error('请填写有效的锁定时长（分钟，正整数）')
      return { login_lock_threshold: threshold, login_lock_minutes: minutes }
    },
    title: () => ({ site_title: String(form.site_title || '').trim() }),
    favicon: () => {
      const mode = siteFaviconModes.some((item) => item.value === form.site_favicon_mode) ? form.site_favicon_mode : 'none'
      if (mode === 'url' && !/^https?:\/\//i.test(String(form.site_favicon_url || '').trim())) {
        throw new Error('图标 URL 必须以 http:// 或 https:// 开头')
      }
      return mode === 'url' ? { site_favicon_mode: mode, site_favicon_url: String(form.site_favicon_url).trim() } : { site_favicon_mode: mode }
    },
    icp: () => ({ site_icp_number: String(form.site_icp_number || '').trim() })
  }
  await runAction(async () => {
    const data = await request('/api/admin/site-settings', { method: 'PUT', body: payloads[group]() })
    applySiteSettingsData(data.settings)
    applySiteSettingsGlobally(data.settings)
  }, '保存成功，已全站生效')
}

function applySiteSettingsGlobally(data) {
  site.apply({
    site_title: data.site_title || '',
    site_favicon_url: data.site_favicon_effective_url || '',
    site_icp_number: data.site_icp_number || ''
  })
}

async function uploadSiteFavicon(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (!/\.(ico|png)$/i.test(file.name)) {
    showFeedback('仅支持 .ico / .png 图标文件', 'warning')
    return
  }
  if (file.size > 200 * 1024) {
    showFeedback('图标文件不能超过 200KB', 'warning')
    return
  }
  siteFaviconUploading.value = true
  const body = new FormData()
  body.append('file', file)
  try {
    // 上传成功即写入并切到 upload 模式（后端已持久化），表单回显 + 全站立即换图标。
    const data = await request('/api/admin/site-settings/favicon', { method: 'POST', body })
    applySiteSettingsData(data.settings)
    applySiteSettingsGlobally(data.settings)
    showFeedback('网站图标已上传并生效')
  } catch (error) {
    showFeedback(error.message || '图标上传失败', 'warning')
  } finally {
    siteFaviconUploading.value = false
  }
}

async function createPaymentTest() {
  await runAction(async () => {
    paymentTestResult.value = await requestPaymentTest('/api/admin/payment-test', { method: 'POST', body: paymentTest.value })
  }, '测试支付单已生成')
}

function openPaymentTest() {
  const paymentUrl = paymentTestResult.value?.payment_submit_url || paymentTestResult.value?.payment_url
  if (!paymentUrl) return
  window.open(buildApiUrl(paymentUrl), '_blank', 'noopener,noreferrer')
}

async function refreshPaymentTest() {
  if (!paymentTestResult.value?.order_id) return
  await runAction(async () => {
    const current = await requestPaymentTest(`/api/admin/payment-test/${paymentTestResult.value.order_id}`)
    paymentTestResult.value = { ...paymentTestResult.value, ...current }
  }, '测试支付状态已刷新')
}

async function simulatePaymentTestSuccess() {
  if (!paymentTestResult.value?.order_id) return
  await runAction(async () => {
    const current = await requestPaymentTest(`/api/admin/payment-test/${paymentTestResult.value.order_id}/simulate-success`, { method: 'POST' })
    paymentTestResult.value = { ...paymentTestResult.value, ...current }
  }, '已模拟支付成功回调')
}

async function requestPaymentTest(path, options) {
  try {
    return await request(path, options)
  } catch (error) {
    if (error.message === 'Not Found') {
      throw new Error('当前后端仍未加载支付测试接口，请重建/重启 backend 容器后再试')
    }
    throw error
  }
}

function formatPaymentMethod(method) {
  return { alipay: '支付宝', wxpay: '微信', epay: '易支付', balance: '余额支付' }[method] || method || '未知方式'
}

function orderPricingDetail(order) {
  if (!order?.pricing_detail) return null
  if (typeof order.pricing_detail === 'object') return order.pricing_detail
  try {
    return JSON.parse(order.pricing_detail)
  } catch {
    return null
  }
}

function orderDiscountLabel(order) {
  return orderPricingDetail(order)?.applied_discount?.label || ''
}

function formatPaymentStatus(status) {
  return {
    pending: '待支付',
    paid: '已支付',
    printing: '打印中',
    completed: '已完成',
    refunded: '已退款',
    print_failed: '打印失败',
    failed: '支付失败',
    closed: '已关闭'
  }[status] || status || '未知'
}

function normalizedPaymentStatus(order) {
  if (order.payment_status) return order.payment_status
  if (['paid', 'printing', 'completed', 'print_failed'].includes(order.status)) return 'paid'
  if (order.status === 'pending') return 'pending'
  return order.status || ''
}

function formatOrderPaymentStatus(order) {
  return formatPaymentStatus(normalizedPaymentStatus(order))
}

function formatPrintStatus(status) {
  return {
    pending: '未开始',
    paid: '待打印',
    printing: '打印中',
    completed: '已完成',
    print_failed: '打印失败'
  }[status] || status || '未知'
}

function paymentStatusClass(order) {
  const status = normalizedPaymentStatus(order)
  if (status === 'paid') return 'success'
  if (['refunded', 'closed', 'failed'].includes(status)) return 'warning'
  return 'info'
}

function printStatusClass(status) {
  if (['printing', 'completed'].includes(status)) return 'success'
  if (status === 'print_failed') return 'warning'
  return 'info'
}

function canDeleteUnpaid(order) {
  return order.status === 'pending' && normalizedPaymentStatus(order) !== 'paid'
}

function canCompleteOrder(order) {
  return ['paid', 'printing', 'print_failed'].includes(order.status)
}

function paymentTestStatusClass(status) {
  if (['paid', 'printing', 'completed'].includes(status)) return 'success'
  if (['print_failed', 'refunded', 'closed', 'failed'].includes(status)) return 'warning'
  return 'info'
}

function normalizePrinterDrivers(rows) {
  const fallback = { id: 'everywhere', label: 'IPP Everywhere / AirPrint / Mopria', recommended: true }
  const drivers = Array.isArray(rows) && rows.length ? rows : [fallback]
  if (!drivers.some((driver) => driver.id === 'everywhere')) {
    return [fallback, ...drivers]
  }
  return drivers
}

function driverConfidenceLabel(confidence) {
  if (confidence === 'high') return '高匹配'
  if (confidence === 'medium') return '可用匹配'
  if (confidence === 'low') return '备选'
  return confidence || ''
}

function formatDriverPackages(hint) {
  const packages = hint?.packages || []
  return packages.length ? `建议包：${packages.join(' / ')}` : ''
}

function isCupsPermissionMessage(message = '') {
  return /(\b4096\b|unauthorized|not-authorized|forbidden|CUPS 拒绝|没有足够的 CUPS|没有足够的打印机管理权限)/i.test(String(message || ''))
}

function driverQuery(context = {}) {
  const source = !context || typeof context.preventDefault === 'function' ? {} : context
  const params = new URLSearchParams()
  if (source.search) params.set('search', source.search)
  if (source.make_model) params.set('make_model', source.make_model)
  if (source.uri) params.set('uri', source.uri)
  if (source.connection_type) params.set('connection_type', source.connection_type)
  const query = params.toString()
  return query ? `/api/admin/printer-drivers?${query}` : '/api/admin/printer-drivers'
}

function connectionTypeFromUri(uri = '') {
  return String(uri).split(':', 1)[0] || ''
}

function currentPrinterDriverContext() {
  const uri = printerForm.value.uri || ''
  const makeModel = printerForm.value.description || printerForm.value.name || ''
  return {
    make_model: makeModel,
    uri,
    connection_type: connectionTypeFromUri(uri),
    info: printerForm.value.description || printerForm.value.name || ''
  }
}

async function refreshPrinterDrivers(context = {}) {
  const result = await request(driverQuery(context))
  printerDrivers.value = normalizePrinterDrivers(result.drivers || [])
  printerDriverAdvice.value = result.recommendation?.install_hint || null
}

async function loadPrinterDrivers(context = {}) {
  await runAction(async () => {
    await refreshPrinterDrivers(context)
  }, '驱动列表已刷新')
}

function openPpdImport() {
  ppdUploadInput.value?.click()
}

async function importPpdDriver(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  const body = new FormData()
  const context = currentPrinterDriverContext()
  body.append('file', file)
  if (context.make_model) body.append('make_model', context.make_model)
  if (context.uri) body.append('uri', context.uri)
  if (context.connection_type) body.append('connection_type', context.connection_type)
  if (context.info) body.append('info', context.info)
  await runAction(async () => {
    const result = await request('/api/admin/printer-drivers/ppd', { method: 'POST', body })
    const importedDrivers = result.drivers?.length ? result.drivers : result.driver ? [result.driver] : []
    await refreshPrinterDrivers({ ...context, search: result.driver?.model || result.driver?.label || '' })
    for (const driver of importedDrivers) {
      if (driver?.id && !printerDrivers.value.some((item) => item.id === driver.id)) {
        printerDrivers.value = normalizePrinterDrivers([driver, ...printerDrivers.value])
      }
    }
    printerDriverAdvice.value = result.recommendation?.install_hint || printerDriverAdvice.value
    if (result.driver?.id) printerForm.value.driver = result.driver.id
  }, '驱动已导入')
}

function closeAddPrinterModal() {
  showAddPrinterModal.value = false
  printerForm.value = { ...emptyPrinter }
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function parsePrinterUri(uri = '') {
  try {
    const parsed = new URL(uri)
    const type = parsed.protocol.replace(':', '')
    return {
      host: parsed.hostname || '',
      connection_type: ['ipp', 'socket', 'lpd'].includes(type) ? type : 'ipp'
    }
  } catch {
    return { host: '', connection_type: 'ipp' }
  }
}

function fillPrinter(printer) {
  printerForm.value = {
    editingName: printer.name,
    name: printer.name,
    uri: printer.uri || printer.system_uri || '',
    driver: printer.driver || 'everywhere',
    location: printer.location || '',
    description: printer.description || '',
    is_default: Boolean(printer.is_default),
    is_enabled: Boolean(printer.is_enabled),
    accepting_jobs: printer.accepting_jobs !== false,
    // 【新增功能】回填彩色/自动双面能力（缺省时按「不支持彩色、支持双面」处理，与后端默认值一致）。
    is_support_color: Boolean(printer.is_support_color),
    is_support_auto_duplex: printer.is_support_auto_duplex !== false
  }
}

// 【新增功能】打开编辑弹窗：先把打印机详情回填到表单，再展示弹窗。
function openPrinterEditor(printer) {
  fillPrinter(printer)
  showAddPrinterModal.value = true
}

async function viewPrinterInfo(printer) {
  await runAction(async () => {
    const [info, jobs] = await Promise.all([
      request(printerApiPath(printer.name)),
      request(printerApiPath(printer.name, '/jobs'))
    ])
    selectedPrinterInfo.value = info
    selectedPrinterJobs.value = jobs.jobs || []
  }, '打印机状态已刷新')
}

async function savePrinter() {
  await runAction(async () => {
    const body = {
      name: printerForm.value.name,
      uri: printerForm.value.uri,
      driver: printerForm.value.driver || 'everywhere',
      location: printerForm.value.location,
      description: printerForm.value.description,
      is_default: Boolean(printerForm.value.is_default),
      is_enabled: Boolean(printerForm.value.is_enabled),
      accepting_jobs: Boolean(printerForm.value.accepting_jobs),
      // 【新增功能】彩色/自动双面能力随打印机一起保存。
      is_support_color: Boolean(printerForm.value.is_support_color),
      is_support_auto_duplex: Boolean(printerForm.value.is_support_auto_duplex)
    }
    if (printerForm.value.editingName) {
      await request(printerApiPath(printerForm.value.editingName), {
        method: 'PATCH',
        body: { ...body, new_name: printerForm.value.name }
      })
    }
    closeAddPrinterModal()
    await loadTab()
  }, '打印机已更新')
}

async function makeDefault(name) {
  await runAction(async () => {
    await request(printerApiPath(name, '/default'), { method: 'PUT' })
    await loadTab()
  }, '默认打印机已更新')
}

async function clearDefault() {
  await runAction(async () => {
    await request('/api/admin/printers/default/clear', { method: 'PUT' })
    await loadTab()
  }, '已取消默认打印机，当前暂未设置默认打印机')
}

async function togglePrinter(printer) {
  await runAction(async () => {
    await request(printerApiPath(printer.name, '/enabled'), { method: 'PUT', body: { enabled: !printer.is_enabled, accepting_jobs: printer.accepting_jobs !== false } })
    await loadTab()
  }, '打印机状态已更新')
}

async function testPrint(name) {
  if (!window.confirm(`是否发送一张测试页到 ${name}？`)) return
  await sendTestPrint(name)
}

function printerApiPath(name, suffix = '') {
  return `/api/admin/printers/${encodeURIComponent(name)}${suffix}`
}

async function sendTestPrint(name) {
  await runAction(async () => {
    await request(printerApiPath(name, '/test-page'), { method: 'POST', body: { copies: 1, duplex: false, page_size: 'A4' } })
    const outcome = askTestPrintOutcome(name)
    if (!outcome) {
      showFeedback('测试页已发送，尚未记录人工确认结果', 'warning')
      return
    }
    await request(printerApiPath(name, '/test-result'), {
      method: 'POST',
      body: {
        success: outcome.success,
        note: outcome.note
      }
    })
    await loadTab()
  }, '测试结果已记录')
}

function askTestPrintOutcome(name) {
  const answer = window.prompt(`样张是否打印成功？（是/否/部分成功）\n打印机：${name}`, '是')
  if (answer === null) return null
  const normalized = answer.trim().toLowerCase()
  if (['是', '成功', 'yes', 'y', 'ok'].includes(normalized)) {
    return { success: true, note: '管理员确认测试页已打印' }
  }
  if (['部分成功', '部分', 'partial', 'partly'].includes(normalized)) {
    return { success: true, note: '部分成功：管理员确认测试页部分打印成功' }
  }
  if (['否', '失败', '未成功', 'no', 'n', 'fail', 'failed'].includes(normalized)) {
    return { success: false, note: '管理员确认测试页未成功打印' }
  }
  return { success: false, note: `管理员输入无法识别：${answer}` }
}

async function deletePrinter(name) {
  await runAction(async () => {
    await request(printerApiPath(name), { method: 'DELETE' })
    await loadTab()
  }, '打印机已删除')
}

watch(tab, loadTab)
onMounted(loadTab)
</script>
