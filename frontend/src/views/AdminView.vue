<template>
  <section class="admin-layout">
    <aside class="admin-menu">
      <button v-for="item in tabs" :key="item.key" :class="{ selected: tab === item.key }" @click="tab = item.key">
        <component :is="item.icon" :size="18" />{{ item.label }}
      </button>
    </aside>

    <!-- 手机端底部 Tab 栏：桌面端默认 display:none，只在 767px 内显示（见 styles.css）。
         后台一共 8 个 Tab，底部栏放不下，所以前 4 个常用 Tab 常驻，其余收进「更多」面板；
         桌面端仍由上面的 .admin-menu 展示全部 Tab，两端共用同一个 tab 状态与 loadTab()。 -->
    <nav class="admin-tabbar" aria-label="后台导航">
      <button
        v-for="item in primaryTabs"
        :key="item.key"
        type="button"
        class="admin-tab-item"
        :class="{ active: tab === item.key }"
        @click="selectTab(item.key)"
      >
        <component :is="item.icon" :size="22" />
        <span>{{ item.label }}</span>
      </button>
      <button
        type="button"
        class="admin-tab-item"
        :class="{ active: moreActive }"
        aria-haspopup="dialog"
        :aria-expanded="moreOpen ? 'true' : 'false'"
        @click="moreOpen = !moreOpen"
      >
        <component :is="moreCurrent ? moreCurrent.icon : MoreHorizontal" :size="22" />
        <span>{{ moreCurrent ? moreCurrent.label : '更多' }}</span>
      </button>
    </nav>

    <div v-if="moreOpen" class="admin-more-mask" @click.self="moreOpen = false">
      <div class="admin-more-sheet" role="dialog" aria-label="更多后台功能">
        <div class="admin-more-head">
          <strong>更多功能</strong>
          <button type="button" class="icon-btn" aria-label="关闭" @click="moreOpen = false">×</button>
        </div>
        <div class="admin-more-list">
          <button
            v-for="item in moreTabs"
            :key="item.key"
            type="button"
            class="admin-more-item"
            :class="{ selected: tab === item.key }"
            @click="selectTab(item.key)"
          >
            <component :is="item.icon" :size="20" />
            <span>{{ item.label }}</span>
          </button>
        </div>
        <RouterLink class="admin-more-back" to="/">返回前台首页</RouterLink>
      </div>
    </div>

    <div class="panel admin-panel">
      <div v-if="feedback" :class="['notice', feedbackType]">{{ feedback }}</div>

      <template v-if="tab === 'dashboard'">
        <p class="eyebrow">后台首页</p>
        <h1>运营概览</h1>
        <div class="metrics-grid">
          <div class="metric-card"><span>订单数</span><strong>{{ dashboard?.totals.orders_count || 0 }}</strong></div>
          <div class="metric-card"><span>收入</span><strong>¥{{ Number(dashboard?.totals.revenue || 0).toFixed(2) }}</strong></div>
          <div class="metric-card"><span>待支付</span><strong>{{ dashboard?.totals.pending_orders || 0 }}</strong></div>
          <div class="metric-card"><span>打印失败</span><strong>{{ dashboard?.totals.failed_prints || 0 }}</strong></div>
          <div class="metric-card"><span>正在打印</span><strong>{{ dashboard?.totals.printing_count || 0 }}</strong></div>
          <div class="metric-card"><span>排队中</span><strong>{{ dashboard?.totals.queue_count || 0 }}</strong></div>
        </div>

        <DailyStatsCard />
      </template>

      <template v-if="tab === 'orders'">
        <h1>订单管理</h1>

        <section class="cache-cleanup-panel print-queue-panel">
          <div class="section-heading compact">
            <div>
              <p class="eyebrow">打印排队</p>
              <h2>实时排队看板</h2>
            </div>
            <button class="secondary-btn" :disabled="queueRefreshing" @click="refreshPrintStatus">
              <RefreshCw :size="18" />{{ queueRefreshing ? '刷新中…' : '刷新打印状态' }}
            </button>
          </div>
          <div class="queue-summary">
            <span class="badge info">正在打印：{{ printQueue.printing_count || 0 }}</span>
            <span class="badge warning">排队中：{{ printQueue.waiting_count || 0 }}</span>
            <span class="badge">队列总数：{{ printQueue.total || 0 }}</span>
          </div>
          <div v-if="(printQueue.items || []).length === 0" class="empty-preview compact-empty">当前没有正在打印或排队的订单</div>
          <div v-else class="queue-list">
            <article v-for="item in printQueue.items" :key="item.id" class="queue-row">
              <span class="queue-position">#{{ item.position }}</span>
              <div class="queue-main">
                <strong>{{ item.id }}</strong>
                <span>{{ item.contact_name || '匿名' }} · {{ item.printer_name || '默认打印机' }} · {{ item.copies || 1 }} 份</span>
              </div>
              <span :class="['badge', item.status === 'printing' ? 'info' : 'warning']">
                {{ item.status === 'printing' ? '正在打印' : '排队中' }}
              </span>
            </article>
          </div>
        </section>

        <section class="cache-cleanup-panel">
          <div class="section-heading compact">
            <div>
              <p class="eyebrow">文件缓存</p>
              <h2>按时段清理</h2>
            </div>
          </div>
          <div class="settings-grid">
            <label class="field-label">开始时间<input v-model="cacheCleanup.start_at" class="input" type="datetime-local" /></label>
            <label class="field-label">结束时间<input v-model="cacheCleanup.end_at" class="input" type="datetime-local" /></label>
          </div>
          <div class="inline-controls">
            <label><input v-model="cacheCleanup.include_order_files" type="checkbox" /> 包含订单关联文件缓存</label>
            <button class="secondary-btn" @click="previewFileCacheCleanup"><Search :size="18" />统计可清理缓存</button>
            <button class="secondary-btn danger" @click="cleanupFileCache"><Trash2 :size="18" />执行清理</button>
          </div>
          <div v-if="cacheCleanupResult" class="cleanup-result">
            <strong>{{ cacheCleanupResult.dry_run ? '统计结果' : '清理结果' }}</strong>
            <span>命中 {{ cacheCleanupResult.matched }} 个文件，已清理 {{ cacheCleanupResult.deleted }} 个，跳过 {{ cacheCleanupResult.skipped }} 个，可释放/已释放 {{ Number(cacheCleanupResult.releasable_mb || 0).toFixed(2) }} MB</span>
            <article v-for="file in cacheCleanupResult.files.slice(0, 12)" :key="file.id" class="cleanup-file-row">
              <span>{{ file.original_name }}</span>
              <small>{{ file.uploaded_at }} · {{ file.action }} · {{ file.reason }} · {{ Number(file.size_mb || 0).toFixed(2) }} MB</small>
            </article>
          </div>
        </section>

        <div class="section-heading compact order-list-heading">
          <div>
            <p class="eyebrow">订单列表</p>
            <h2>最近订单</h2>
          </div>
          <button class="secondary-btn danger" :disabled="unpaidOrdersCount === 0" @click="deleteAllUnpaidOrders">
            <Trash2 :size="18" />删除全部未支付<span v-if="unpaidOrdersCount">（{{ unpaidOrdersCount }}）</span>
          </button>
        </div>

        <div class="order-list">
          <article v-for="order in orders" :key="order.id" class="order-row">
            <div class="order-main">
              <strong>{{ order.id }}</strong>
              <span>创建 {{ order.created_at || '-' }}</span>
              <span>打印机 {{ order.printer_name || '默认打印机' }}</span>
            </div>
            <div class="order-money">
              <strong>¥{{ Number(order.total_amount).toFixed(2) }}</strong>
              <span v-if="Number(order.discount_amount || 0) > 0">优惠 ¥{{ Number(order.discount_amount || 0).toFixed(2) }}</span>
              <span>{{ formatPaymentMethod(order.payment_method) }}</span>
            </div>
            <div class="printer-badges order-statuses">
              <span :class="['badge', paymentStatusClass(order)]">支付状态：{{ formatOrderPaymentStatus(order) }}</span>
              <span :class="['badge', printStatusClass(order.status)]">打印状态：{{ formatPrintStatus(order.status) }}</span>
            </div>
            <div class="row-actions">
              <button class="secondary-btn small" @click="loadOrderDetail(order.id)"><Eye :size="16" />详情</button>
              <button v-if="canCompleteOrder(order)" class="secondary-btn small" @click="completeOrder(order.id)">完成</button>
              <button v-if="!canDeleteUnpaid(order)" class="secondary-btn small danger" @click="deleteOrder(order)"><Trash2 :size="16" />删除订单</button>
              <button v-if="canDeleteUnpaid(order)" class="secondary-btn small danger" @click="deleteUnpaidOrder(order)"><Trash2 :size="16" />删除未支付</button>
            </div>
          </article>
        </div>
        <div v-if="orders.length === 0" class="empty-preview compact-empty">暂无订单</div>

        <section v-if="selectedOrderDetail" class="order-detail-panel">
          <div class="section-heading compact">
            <div>
              <p class="eyebrow">订单详情</p>
              <h2>{{ selectedOrderDetail.order.id }}</h2>
            </div>
            <button class="secondary-btn small" @click="closeOrderDetail">关闭</button>
          </div>
          <div class="detail-grid">
            <span>订单号：{{ selectedOrderDetail.order.id }}</span>
            <span>打印人：{{ selectedOrderDetail.order.contact_name || '-' }}</span>
            <span>联系电话：{{ selectedOrderDetail.order.contact_phone || '-' }}</span>
            <span>金额：¥{{ Number(selectedOrderDetail.order.total_amount || 0).toFixed(2) }}</span>
            <span>原价：¥{{ Number(selectedOrderDetail.order.base_amount || selectedOrderDetail.order.total_amount || 0).toFixed(2) }}</span>
            <span>优惠：¥{{ Number(selectedOrderDetail.order.discount_amount || 0).toFixed(2) }}{{ orderDiscountLabel(selectedOrderDetail.order) ? ` · ${orderDiscountLabel(selectedOrderDetail.order)}` : '' }}</span>
            <span>计费张数：{{ selectedOrderDetail.order.sheet_count || 0 }} 张</span>
            <span>支付方式：{{ formatPaymentMethod(selectedOrderDetail.order.payment_method) }}</span>
            <span>支付状态：{{ formatOrderPaymentStatus(selectedOrderDetail.order) }}</span>
            <span>打印状态：{{ formatPrintStatus(selectedOrderDetail.order.status) }}</span>
            <span>支付时间：{{ selectedOrderDetail.order.payment_paid_at || selectedOrderDetail.order.paid_at || '-' }}</span>
            <span>打印时间：{{ selectedOrderDetail.order.printed_at || '-' }}</span>
            <span>份数：{{ selectedOrderDetail.order.copies || 1 }}</span>
            <span>双面：{{ selectedOrderDetail.order.is_double_sided ? '含双面文档（见下方各文件）' : '全部单面' }}</span>
            <span>打印机：{{ selectedOrderDetail.order.printer_name || '默认打印机' }}</span>
            <span>用户：{{ selectedOrderDetail.user.username || '访客/已删除用户' }}</span>
            <span>创建：{{ selectedOrderDetail.order.created_at || '-' }}</span>
            <span>易支付交易号：{{ selectedOrderDetail.order.epay_trade_no || '-' }}</span>
          </div>

          <h2>上传文件</h2>
          <article v-for="file in selectedOrderDetail.files" :key="file.id" class="order-file-row">
            <div>
              <strong>{{ file.original_name }}</strong>
              <span>{{ file.page_count || 0 }} 页 · {{ Number(file.file_size || 0).toFixed(2) }} MB · {{ file.uploaded_at || '-' }}</span>
              <small>{{ file.status || 'unknown' }} · {{ file.pdf_exists ? 'PDF 可预览' : 'PDF 缓存不存在' }}</small>
            </div>
            <div class="printer-badges">
                  <span :class="['badge', file.is_safe ? 'success' : 'warning']">{{ file.is_safe ? '安全' : '已拦截' }}</span>
                  <span class="badge info">覆盖率 {{ Number(file.black_coverage || 0).toFixed(1) }}%</span>
                  <span :class="['badge', file.is_double_sided ? 'success' : 'info']">{{ file.is_double_sided ? '双面' : '单面' }}</span>
                </div>
            <button class="secondary-btn small" :disabled="!file.preview_url" @click="previewOrderFile(file)"><Eye :size="16" />预览</button>
          </article>
          <div v-if="selectedOrderDetail.files.length === 0" class="empty-preview compact-empty">该订单没有关联文件</div>

          <div v-if="selectedOrderFile" class="admin-preview-panel">
            <div class="section-heading compact">
              <h2>{{ selectedOrderFile.original_name }}</h2>
              <button class="secondary-btn small" @click="selectedOrderFile = null">关闭预览</button>
            </div>
            <iframe :src="selectedOrderFile.preview_url" title="订单文件预览"></iframe>
          </div>
        </section>
      </template>

      <template v-if="tab === 'users'">
        <div class="section-heading compact">
          <div>
            <p class="eyebrow">管理员</p>
            <h1>用户管理</h1>
          </div>
          <button class="secondary-btn" @click="resetUserForm"><Plus :size="18" />新增用户</button>
        </div>

        <form class="admin-form" @submit.prevent="saveUser">
          <div class="settings-grid">
            <label class="field-label">用户名<input v-model="userForm.username" class="input" required /></label>
            <label class="field-label">密码<input v-model="userForm.password" class="input" type="password" :required="!userForm.id" :placeholder="userForm.id ? '留空则不修改' : '8-64 位'" /></label>
            <label class="field-label">邮箱<input v-model="userForm.email" class="input" type="email" /></label>
            <label class="field-label">手机号<input v-model="userForm.phone" class="input" /></label>
            <label class="field-label">{{ userForm.id ? '账户余额' : '初始余额' }}<input v-model.number="userForm.balance" class="input" type="number" min="0" step="0.01" /></label>
          </div>
          <div class="inline-controls">
            <label><input v-model="userForm.is_admin" type="checkbox" /> 管理员</label>
            <label><input v-model="userForm.is_active" type="checkbox" /> 启用账户</label>
            <button class="primary-btn" type="submit"><Save :size="18" />{{ userForm.id ? '保存修改' : '创建用户' }}</button>
          </div>
        </form>

        <article v-for="user in users" :key="user.id" class="user-row">
          <div>
            <strong>{{ user.username }}</strong>
            <span>{{ user.email || '未填邮箱' }} · {{ user.phone || '未填手机号' }}</span>
            <small>{{ user.id }}</small>
          </div>
          <div class="printer-badges">
            <span :class="['badge', user.is_active ? 'success' : 'warning']">{{ user.is_active ? '启用' : '已封禁' }}</span>
            <span v-if="user.is_admin" class="badge info">管理员</span>
          </div>
          <strong>¥{{ Number(user.balance || 0).toFixed(2) }}</strong>
          <label class="balance-control">
            <span>余额增减</span>
            <input v-model.number="balanceDeltas[user.id]" class="input" type="number" step="0.01" placeholder="例如 10" />
          </label>
          <label class="balance-control">
            <span>修改余额</span>
            <input v-model.number="balanceTargets[user.id]" class="input" type="number" min="0" step="0.01" placeholder="例如 20" />
          </label>
          <div class="row-actions">
            <button class="secondary-btn small" @click="fillUser(user)"><Pencil :size="16" />编辑</button>
            <button class="secondary-btn small" @click="adjustBalance(user.id)"><Plus :size="16" />加减余额</button>
            <button class="secondary-btn small" @click="setBalance(user.id)"><Save :size="16" />修改余额</button>
            <button class="secondary-btn small" @click="toggleUser(user)"><Power :size="16" />{{ user.is_active ? '封禁' : '解封' }}</button>
            <button class="secondary-btn small danger" :disabled="!!userDeleteBlockReason(user)" :title="userDeleteBlockReason(user) || `删除 ${user.username}`" @click="deleteUser(user)"><Trash2 :size="16" />删除</button>
          </div>
        </article>
        <div v-if="users.length === 0" class="empty-preview compact-empty">暂无用户</div>
      </template>

      <template v-if="tab === 'settings'">
        <h1>系统设置</h1>
        <div class="field-label">
          <span>价格模式</span>
          <div class="segmented">
            <button type="button" :class="{ selected: settings.pricing_mode !== 'coverage_tiered' }" :aria-pressed="settings.pricing_mode !== 'coverage_tiered'" @click="settings.pricing_mode = 'standard'">
              标准页数计费
            </button>
            <button type="button" :class="{ selected: settings.pricing_mode === 'coverage_tiered' }" :aria-pressed="settings.pricing_mode === 'coverage_tiered'" @click="settings.pricing_mode = 'coverage_tiered'">
              覆盖率阶梯计费
            </button>
          </div>
        </div>
        <div class="settings-grid">
          <label v-for="key in visiblePricingKeys" :key="key" class="field-label">{{ settingLabels[key] }}<input v-model="settings[key]" class="input" /></label>
        </div>
        <div class="settings-grid">
          <label v-for="key in commonSettingKeys" :key="key" class="field-label">{{ settingLabels[key] }}<input v-model="settings[key]" class="input" /></label>
        </div>

        <section class="admin-form">
          <div class="section-heading compact">
            <h2>批量打印折扣</h2>
            <button class="secondary-btn small" type="button" @click="addBulkDiscountRule"><Plus :size="16" />新增规则</button>
          </div>
          <div class="inline-controls">
            <label><input v-model="settings.bulk_discount_enabled" type="checkbox" /> 启用批量打印折扣</label>
          </div>
          <div v-for="(rule, index) in settings.bulk_discount_rules" :key="index" class="settings-grid">
            <label class="field-label">满多少张<input v-model.number="rule.min_sheets" class="input" type="number" min="1" step="1" /></label>
            <label class="field-label">折扣（%）<input v-model.number="rule.discount_percent" class="input" type="number" min="1" max="100" step="1" /></label>
            <button class="secondary-btn small danger" type="button" @click="removeBulkDiscountRule(index)"><Trash2 :size="16" />删除规则</button>
          </div>
          <div v-if="!settings.bulk_discount_rules?.length" class="empty-preview compact-empty">暂无批量折扣规则</div>
        </section>

        <section class="admin-form">
          <div class="section-heading compact">
            <h2>每日限时特价</h2>
          </div>
          <div class="inline-controls">
            <label><input v-model="settings.daily_limited_offer_enabled" type="checkbox" /> 启用每日限时特价</label>
            <label><input v-model="settings.daily_limited_offer_all_day" type="checkbox" /> 全天生效</label>
            <label><input v-model="settings.daily_limited_offer_free" type="checkbox" /> 完全免费（0 元）</label>
          </div>
          <div class="settings-grid">
            <label :class="['field-label', { disabled: settings.daily_limited_offer_all_day }]">开始时间<input v-model="settings.daily_limited_offer_start_time" class="input" type="time" :disabled="settings.daily_limited_offer_all_day" /></label>
            <label :class="['field-label', { disabled: settings.daily_limited_offer_all_day }]">结束时间<input v-model="settings.daily_limited_offer_end_time" class="input" type="time" :disabled="settings.daily_limited_offer_all_day" /></label>
            <label class="field-label">每日限购张数<input v-model.number="settings.daily_limited_offer_sheet_quota" class="input" type="number" min="0" step="1" /></label>
            <label :class="['field-label', { disabled: settings.daily_limited_offer_free }]">特价折扣（%）<input v-model.number="settings.daily_limited_offer_discount_percent" class="input" type="number" min="1" max="100" step="1" :disabled="settings.daily_limited_offer_free" /></label>
          </div>
          <small class="field-hint">限时特价按全站每日张数额度共享；当前订单张数超过剩余额度时不享受限时特价。勾选“全天生效”后忽略开始/结束时间，当日额度内全天享受特价。勾选“完全免费”后，命中额度的订单在生效时段内为 0 元并直接免支付派发打印，折扣百分比将被忽略。</small>
        </section>

        <button class="primary-btn" @click="saveSettings"><Save :size="18" />保存设置</button>
      </template>

      <template v-if="tab === 'payment'">
        <h1>易支付配置</h1>
        <div v-if="paymentSettings.validation" :class="['notice', paymentSettings.validation.ready ? 'success' : 'warning']">
          <strong>{{ paymentSettings.validation.ready ? '易支付配置已就绪' : '易支付配置未就绪' }}</strong>
          <div v-for="item in paymentSettings.validation.errors || []" :key="item">{{ item }}</div>
          <div v-for="item in paymentSettings.validation.warnings || []" :key="item">{{ item }}</div>
        </div>
        <div class="settings-grid">
          <label class="field-label">网关地址<input v-model="paymentSettings.epay_gateway" class="input" /></label>
          <label class="field-label">商户 ID<input v-model="paymentSettings.epay_pid" class="input" /></label>
          <label class="field-label">商户密钥<input v-model="paymentSettings.epay_key" class="input" type="password" :placeholder="paymentSettings.epay_key_masked" /></label>
          <label class="field-label">公网回调地址<input v-model="paymentSettings.public_base_url" class="input" /></label>
          <label class="field-label">前端返回地址<input v-model="paymentSettings.frontend_base_url" class="input" /></label>
        </div>
        <button class="primary-btn" @click="savePaymentSettings"><Save :size="18" />保存支付配置</button>

        <section class="payment-test-panel">
          <div class="section-heading compact">
            <div>
              <p class="eyebrow">支付自测</p>
              <h2>创建测试支付单</h2>
            </div>
          </div>
          <div class="settings-grid">
            <label class="field-label">支付方式
              <select v-model="paymentTest.payment_method" class="input">
                <option value="alipay">支付宝</option>
                <option value="wxpay">微信</option>
              </select>
            </label>
            <label class="field-label">测试金额<input v-model.number="paymentTest.amount" class="input" type="number" min="0.01" step="0.01" /></label>
          </div>
          <div class="inline-controls">
            <button class="secondary-btn" :disabled="paymentSettings.validation && !paymentSettings.validation.ready" @click="createPaymentTest"><CreditCard :size="18" />发起测试支付</button>
            <button class="secondary-btn" :disabled="!paymentTestResult?.payment_url || paymentTestResult?.status !== 'pending'" @click="openPaymentTest"><ExternalLink :size="18" />打开测试支付页</button>
            <button class="secondary-btn" :disabled="!paymentTestResult?.order_id" @click="refreshPaymentTest"><RefreshCw :size="18" />刷新测试状态</button>
            <button class="secondary-btn" :disabled="!paymentTestResult?.order_id || paymentTestResult?.status !== 'pending'" @click="simulatePaymentTestSuccess"><CheckCircle :size="18" />模拟支付成功</button>
          </div>
          <div v-if="paymentTestResult" class="cleanup-result">
            <strong>测试单 {{ paymentTestResult.order_id }}</strong>
            <span>金额 ¥{{ Number(paymentTestResult.amount || 0).toFixed(2) }} · {{ formatPaymentMethod(paymentTestResult.payment_method) }} · {{ paymentTestResult.gateway || '本地测试单' }}</span>
            <div class="printer-badges">
              <span :class="['badge', paymentTestStatusClass(paymentTestResult.status)]">订单 {{ formatPaymentStatus(paymentTestResult.status) }}</span>
              <span :class="['badge', paymentTestStatusClass(paymentTestResult.payment_status)]">支付 {{ formatPaymentStatus(paymentTestResult.payment_status) }}</span>
              <span v-if="paymentTestResult.paid_at" class="badge success">已回调 {{ paymentTestResult.paid_at }}</span>
            </div>
            <small>提交地址 {{ paymentTestResult.payment_url }} · 签名类型 {{ paymentTestResult.params?.sign_type || 'MD5' }} · 支付类型 {{ paymentTestResult.params?.type || paymentTestResult.payment_method }}</small>
          </div>
        </section>
      </template>

      <template v-if="tab === 'printers'">
        <div class="section-heading compact">
          <div>
            <p class="eyebrow">打印机管理</p>
            <h1>打印机</h1>
          </div>
          <div class="row-actions">
            <button class="secondary-btn" @click="loadTab"><RefreshCw :size="18" />刷新</button>
          </div>
        </div>

        <div class="printer-dashboard">
          <div class="printer-stat-card">
            <div class="stat-icon">{{ printerSystem.connected ? '🟢' : '🔴' }}</div>
            <div class="stat-content">
              <span class="stat-label">CUPS 连接</span>
              <strong class="stat-value">{{ printerSystem.connected ? '已连接' : '未连接' }}</strong>
            </div>
          </div>
          <div class="printer-stat-card">
            <div class="stat-icon">🖨️</div>
            <div class="stat-content">
              <span class="stat-label">打印机数量</span>
              <strong class="stat-value">{{ printerSystem.printer_count || 0 }}</strong>
            </div>
          </div>
          <div class="printer-stat-card">
            <div class="stat-icon">🎯</div>
            <div class="stat-content">
              <span class="stat-label">默认打印机</span>
              <strong class="stat-value">{{ printerSystem.default_printer || '未设置' }}</strong>
            </div>
          </div>
        </div>

        <div v-if="printerSystem.diagnostics?.length" class="printer-diagnostics">
          <small v-for="item in printerSystem.diagnostics" :key="`${item.source}-${item.message}`">{{ item.message }} {{ item.hint }}</small>
        </div>

        <section class="admin-form">
          <div class="section-heading compact">
            <h2>CUPS 服务器配置</h2>
          </div>
          <div class="settings-grid">
            <label class="field-label">{{ settingLabels.cups_server }}<input v-model="settings.cups_server" class="input" placeholder="例如: 192.168.1.100:631" /></label>
          </div>
          <small class="field-hint">保存后会自动刷新打印机列表与默认打印机状态。CUPS 服务器地址格式为: 主机名:端口 或 IP:端口，默认端口为 631。</small>
          <button class="primary-btn" @click="saveSettings({ reloadPrinters: true })"><Save :size="18" />保存配置</button>
        </section>

        <div class="printer-list">
          <div v-if="printers.length === 0" class="empty-state">
            <Printer :size="48" />
            <p>暂无打印机</p>
            <p class="empty-hint">请在 CUPS 服务器上添加打印机后刷新列表</p>
          </div>
          <div v-else class="printer-cards">
            <div v-for="printer in printers" :key="printer.name" class="printer-card">
              <div class="printer-card-header">
                <div class="printer-status" :class="printer.state">
                  {{ printer.state === 'idle' ? '空闲' : printer.state === 'processing' ? '打印中' : printer.state === 'stopped' ? '已停止' : '未知' }}
                </div>
                <div v-if="printer.is_default" class="printer-default-badge">默认</div>
              </div>
              <h3 class="printer-name">{{ printer.display_name || printer.name }}</h3>
              <p class="printer-model">{{ printer.driver_label || printer.driver }}</p>
              <div class="printer-meta">
                <span><Globe :size="14" />{{ printer.uri || '未配置' }}</span>
                <span><MapPin :size="14" />{{ printer.location || '未指定位置' }}</span>
              </div>
              <div class="printer-info-row">
                <span>队列任务：{{ printer.queued_jobs || 0 }}</span>
                <span>状态：{{ printer.is_enabled ? '启用' : '停用' }}</span>
              </div>
              <!-- 【新增功能】打印机能力标识：这两个开关决定前台是否展示「彩色打印」「自动双面打印」。 -->
              <div class="printer-caps">
                <span class="cap-tag" :class="printer.is_support_color ? 'on color' : 'off'">
                  <span class="cap-dot color"></span>{{ printer.is_support_color ? '支持彩色打印' : '仅黑白打印' }}
                </span>
                <span class="cap-tag" :class="printer.is_support_auto_duplex ? 'on duplex' : 'off'">
                  <span class="cap-dot duplex"></span>{{ printer.is_support_auto_duplex ? '支持自动双面' : '仅单面打印' }}
                </span>
              </div>
              <div class="printer-actions">
                <button class="action-btn" @click="openPrinterEditor(printer)" title="编辑打印机（彩色 / 自动双面能力）">
                  <Pencil :size="16" />
                </button>
                <button v-if="!printer.is_default" class="action-btn" @click="makeDefault(printer.name)" title="设置默认打印机">
                  <CheckCircle :size="16" />
                </button>
                <button v-else class="action-btn" @click="clearDefault()" title="取消默认打印机">
                  <XCircle :size="16" />
                </button>
                <button class="action-btn" @click="testPrint(printer.name)" title="打印测试">
                  <Printer :size="16" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <section v-if="selectedPrinterInfo" class="scan-section">
          <div class="section-heading compact">
            <div>
              <p class="eyebrow">实时状态</p>
              <h2>{{ selectedPrinterInfo.name }}</h2>
            </div>
            <button class="secondary-btn" @click="selectedPrinterInfo = null"><RotateCcw :size="18" />收起</button>
          </div>
          <div class="settings-grid">
            <div class="stat-card"><span>状态</span><strong>{{ selectedPrinterInfo.state_text || selectedPrinterInfo.state }}</strong></div>
            <div class="stat-card"><span>队列任务</span><strong>{{ selectedPrinterInfo.queued_jobs || 0 }}</strong></div>
            <div class="stat-card"><span>持续时间</span><strong>{{ selectedPrinterInfo.state_duration_seconds || 0 }} 秒</strong></div>
            <div class="stat-card"><span>固件</span><strong>{{ selectedPrinterInfo.firmware_version || '-' }}</strong></div>
          </div>
          <div class="printer-badges">
            <span v-for="reason in selectedPrinterInfo.state_reasons || []" :key="reason" class="badge info">{{ reason }}</span>
            <span v-for="media in selectedPrinterInfo.media_ready || []" :key="media" class="badge success">{{ media }}</span>
          </div>
          <div v-if="selectedPrinterJobs.length" class="printer-jobs">
            <h3>队列任务</h3>
            <article v-for="job in selectedPrinterJobs" :key="job.id" class="job-row">
              <strong>#{{ job.id }} {{ job.title }}</strong>
              <span>{{ job.state_text || job.state }} · {{ formatDateTime(job.created_at) }} · {{ Math.round((job.size || 0) / 1024) }} KB</span>
            </article>
          </div>
        </section>

        <div v-if="showAddPrinterModal" class="modal-overlay" @click.self="closeAddPrinterModal">
          <div class="modal-content">
            <div class="modal-header">
              <h2>编辑打印机</h2>
              <button class="close-btn" @click="closeAddPrinterModal">×</button>
            </div>
            <div class="modal-body">
              <form @submit.prevent="savePrinter" class="add-printer-form">
                <div class="form-row">
                  <label>队列名称</label>
                  <input v-model="printerForm.name" class="input" readonly />
                </div>

                <div class="form-row">
                  <label>设备 URI</label>
                  <input v-model="printerForm.uri" class="input" />
                </div>

                <div class="form-row">
                  <label>驱动</label>
                  <select v-model="printerForm.driver" class="input">
                    <option v-for="driver in printerDrivers" :key="driver.id" :value="driver.id">
                      {{ driver.recommended ? '★ ' : '' }}{{ driver.label }}{{ driver.source === 'local-ppd' ? ' (已导入)' : '' }}
                    </option>
                  </select>
                  <small v-if="selectedPrinterDriver?.recommendation_reason">{{ selectedPrinterDriver.recommendation_reason }}</small>
                </div>

                <div class="form-row">
                  <label>位置</label>
                  <input v-model="printerForm.location" class="input" placeholder="例如：会议室 A" />
                </div>

                <div class="form-row">
                  <label>说明</label>
                  <input v-model="printerForm.description" class="input" placeholder="打印机描述" />
                </div>

                <div class="form-row checkboxes">
                  <label><input v-model="printerForm.is_default" type="checkbox" /> 设置为默认打印机</label>
                  <label><input v-model="printerForm.is_enabled" type="checkbox" /> 启用打印机</label>
                  <label><input v-model="printerForm.accepting_jobs" type="checkbox" /> 接收打印任务</label>
                </div>

                <!-- 【新增功能】打印机能力：持久化到 printers 表，并决定前台打印页是否展示对应选项。 -->
                <div class="form-row capability-row">
                  <div class="capability-heading">打印机能力</div>
                  <label class="capability-toggle">
                    <input v-model="printerForm.is_support_color" type="checkbox" />
                    <span class="capability-text">
                      <strong><span class="swatch color"></span>支持彩色打印</strong>
                      <small>开启后前台展示「彩色打印」，勾选彩色时文件按原始色彩直接送印；关闭后前台完全隐藏该选项，并按黑白流程处理。</small>
                    </span>
                  </label>
                  <label class="capability-toggle">
                    <input v-model="printerForm.is_support_auto_duplex" type="checkbox" />
                    <span class="capability-text">
                      <strong><span class="swatch duplex"></span>支持自动双面打印</strong>
                      <small>开启后前台展示「自动双面」；关闭后前台完全隐藏该选项，所有任务按单面打印。</small>
                    </span>
                  </label>
                </div>

                <div class="form-actions">
                  <button type="button" class="secondary-btn" @click="closeAddPrinterModal">取消</button>
                  <button type="submit" class="primary-btn">保存修改</button>
                </div>
              </form>
            </div>
          </div>
        </div>
      </template>

      <template v-if="tab === 'backups'">
        <div class="section-heading compact">
          <div>
            <p class="eyebrow">数据安全</p>
            <h1>备份与恢复</h1>
          </div>
          <div class="row-actions">
            <button class="secondary-btn" @click="loadTab"><RefreshCw :size="18" />刷新</button>
          </div>
        </div>

        <section class="backup-actions-panel">
          <div class="section-heading compact">
            <div>
              <p class="eyebrow">一键备份</p>
              <h2>创建完整数据包</h2>
            </div>
            <div class="segmented-control">
              <button :class="{ selected: backupCreate.archive_format === 'zip' }" type="button" @click="backupCreate.archive_format = 'zip'">ZIP</button>
              <button :class="{ selected: backupCreate.archive_format === 'tar.gz' }" type="button" @click="backupCreate.archive_format = 'tar.gz'">TAR.GZ</button>
            </div>
          </div>
          <div class="backup-summary-grid">
            <div><strong>数据库</strong><span>订单、用户、支付、配置、打印机</span></div>
            <div><strong>上传文件</strong><span>原始文件、转换 PDF、预览缓存</span></div>
            <div><strong>配置与日志</strong><span>compose/env 配置和 logs 目录</span></div>
          </div>
          <button class="primary-btn" :disabled="backupBusy" @click="createBackup"><Archive :size="18" />{{ backupBusy ? '正在备份' : '立即备份' }}</button>
        </section>

        <section class="backup-actions-panel">
          <div class="section-heading compact">
            <div>
              <p class="eyebrow">自动备份</p>
              <h2>执行策略</h2>
            </div>
          </div>
          <div class="settings-grid">
            <label class="field-label">执行频率
              <select v-model="backupPolicy.frequency" class="input">
                <option value="daily">每天</option>
                <option value="weekly">每周</option>
              </select>
            </label>
            <label class="field-label">执行时间<input v-model="backupPolicy.time" class="input" type="time" /></label>
            <label v-if="backupPolicy.frequency === 'weekly'" class="field-label">每周几
              <select v-model.number="backupPolicy.weekday" class="input">
                <option v-for="(label, index) in weekdayLabels" :key="label" :value="index">{{ label }}</option>
              </select>
            </label>
            <label class="field-label">保留数量<input v-model.number="backupPolicy.retention_count" class="input" type="number" min="1" max="365" step="1" /></label>
          </div>
          <div class="inline-controls">
            <label><input v-model="backupPolicy.enabled" type="checkbox" /> 启用自动备份</label>
            <button class="primary-btn" @click="saveBackupPolicy"><Save :size="18" />保存策略</button>
            <span class="field-hint">上次执行：{{ backupPolicy.last_run_at || '尚未执行' }}</span>
          </div>
        </section>

        <section class="backup-actions-panel">
          <div class="section-heading compact">
            <div>
              <p class="eyebrow">恢复数据</p>
              <h2>上传备份文件</h2>
            </div>
          </div>
          <label :class="['restore-dropzone', { active: restoreDragging }]" @dragover.prevent="restoreDragging = true" @dragleave.prevent="restoreDragging = false" @drop.prevent="dropRestoreFile">
            <UploadCloud :size="30" />
            <span>拖拽备份文件到这里，或点击选择</span>
            <small>支持 backup_*.zip 和 backup_*.tar.gz；恢复前会解析校验备份完整性</small>
            <input type="file" accept=".zip,.tar.gz,.tgz" @change="chooseRestoreFile" />
          </label>
          <div v-if="restoreInfo" class="restore-confirm">
            <strong>{{ restoreInfo.filename }}</strong>
            <span>备份时间：{{ formatDateTime(restoreInfo.backup_time) }} · 数据版本：{{ restoreInfo.data_version }} · 格式：{{ restoreInfo.archive_format }}</span>
            <div class="printer-badges">
              <span class="badge success">数据库</span>
              <span :class="['badge', restoreInfo.content?.uploads ? 'success' : 'info']">上传文件 {{ restoreInfo.content?.uploads ? '包含' : '未包含' }}</span>
              <span :class="['badge', restoreInfo.content?.logs ? 'success' : 'info']">日志 {{ restoreInfo.content?.logs ? '包含' : '未包含' }}</span>
              <span class="badge info">配置 {{ restoreInfo.content?.config_files?.length || 0 }} 个</span>
            </div>
            <button class="secondary-btn danger" :disabled="restoreBusy" @click="restoreBackup"><RotateCcw :size="18" />确认覆盖并恢复</button>
          </div>
        </section>

        <section class="backup-list-section">
          <div class="section-heading compact">
            <div>
              <p class="eyebrow">备份列表</p>
              <h2>可下载归档</h2>
            </div>
          </div>
          <article v-for="backup in backups" :key="backup.filename" class="backup-row">
            <div>
              <strong>{{ backup.filename }}</strong>
              <span>{{ formatDateTime(backup.backup_time) }} · {{ backup.data_version }} · {{ backup.archive_format }}</span>
              <small>{{ backup.created_by === 'auto' ? '自动备份' : '手动备份' }} · {{ Number(backup.size_mb || 0).toFixed(2) }} MB</small>
            </div>
            <div class="printer-badges">
              <span class="badge success">数据库</span>
              <span v-if="backup.content?.uploads" class="badge info">上传文件</span>
              <span v-if="backup.content?.logs" class="badge info">日志</span>
              <span v-if="backup.content?.config_files?.length" class="badge info">配置</span>
            </div>
            <div class="row-actions">
              <button class="secondary-btn small" @click="downloadBackup(backup)"><Download :size="16" />下载</button>
              <button class="secondary-btn small danger" @click="deleteBackup(backup)"><Trash2 :size="16" />删除</button>
            </div>
          </article>
          <div v-if="backups.length === 0" class="empty-preview compact-empty">暂无备份</div>
        </section>
      </template>

      <template v-if="tab === 'redemptions'">
        <div class="section-heading compact redemption-heading">
          <div>
            <p class="eyebrow">兑换码</p>
            <h1>兑换码管理</h1>
          </div>
          <div class="row-actions">
            <label class="redemption-search">
              <input v-model.trim="redemptionSearch" class="input" placeholder="搜索兑换码" @keyup.enter="loadRedemptions" />
            </label>
            <button class="secondary-btn" @click="openAddRedemption"><Plus :size="18" />手动新增</button>
            <button class="secondary-btn" @click="openBatchRedemption"><RefreshCw :size="18" />批量生成</button>
          </div>
        </div>

        <!-- 表格精简为 5 列（兑换码 / 面额 / 有效期 / 使用状态 / 操作），其余次要信息移入「详情」抽屉。
             外层滚动容器只是安全网：列宽自适应，正常情况下不会出现横向滚动条；
             万一容器过窄而横向溢出，「操作」列会 sticky 固定在右侧，详情/删除始终可见可点击。 -->
        <div class="redemption-table-scroll">
          <div class="redemption-table">
            <div class="redemption-table-head">
              <span>兑换码</span>
              <span>兑换面额</span>
              <span>有效期</span>
              <span>使用状态</span>
              <span class="redemption-cell-actions">操作</span>
            </div>
            <article v-for="code in redemptions" :key="code.id" class="redemption-row">
              <strong class="redemption-code" :title="code.code">{{ code.code }}</strong>
              <strong class="redemption-amount">¥{{ Number(code.amount).toFixed(2) }}</strong>
              <!-- 【新增功能】有效期列兼容两种配置：指定到期日期的码只显示到期时刻；
                   按天数的码额外标明天数（存量数据与之前显示一致，仅多了「N 天 ·」前缀）。 -->
              <span>{{ redemptionExpiryText(code) }}</span>
              <span :class="['badge', redemptionStatusClass(code.status)]">{{ redemptionStatusLabel(code.status) }}</span>
              <div class="row-actions redemption-cell-actions">
                <button class="secondary-btn small" @click="openRedemptionDetail(code)"><Eye :size="16" />详情</button>
                <button class="secondary-btn small danger" @click="deleteRedemption(code)"><Trash2 :size="16" />删除</button>
              </div>
            </article>
            <div v-if="redemptions.length === 0" class="empty-preview compact-empty">暂无兑换码</div>
          </div>
        </div>
        <div v-if="redemptionsHasMore" class="orders-more">
          <button class="secondary-btn load-more-btn" @click="loadMoreRedemptions" :disabled="redemptionLoadingMore">{{ redemptionLoadingMore ? '加载中...' : '加载更多' }}</button>
        </div>

        <!-- 手动新增兑换码 -->
        <div v-if="showAddRedemptionModal" class="modal-overlay" @click.self="closeAddRedemptionModal">
          <div class="modal-content redemption-modal">
            <div class="modal-header redemption-modal-header">
              <h2>手动新增兑换码</h2>
              <button class="close-btn" @click="closeAddRedemptionModal">×</button>
            </div>
            <div class="modal-body">
              <form @submit.prevent="saveAddRedemption" class="add-printer-form redemption-form">
                <div class="form-row">
                  <label>兑换码</label>
                  <input v-model.trim="redemptionForm.code" class="input" placeholder="自定义兑换码（留空随机生成）" maxlength="64" />
                </div>
                <div class="form-row">
                  <label>兑换面额（元）</label>
                  <input v-model.number="redemptionForm.amount" class="input" type="number" min="0.01" step="0.01" required />
                </div>
                <div class="form-row">
                  <label>可用次数</label>
                  <input v-model.number="redemptionForm.usable_count" class="input" type="number" min="1" step="1" />
                </div>
                <!-- 【新增功能】有效期支持「按天数」或「直接指定到期日期」两种互斥方式：
                     分段切换后只保留其中一种输入（按天数→数字输入框；指定到期日期→原生日期选择器），
                     从交互上保证两种方式不会同时生效。日期模式提交 expiry_mode='date' + expire_date。 -->
                <div class="form-row expiry-row">
                  <label>有效期</label>
                  <div class="expiry-control">
                    <div class="segmented expiry-mode">
                      <button type="button" :class="{ selected: redemptionForm.expiry_mode === 'days' }" @click="redemptionForm.expiry_mode = 'days'">按天数</button>
                      <button type="button" :class="{ selected: redemptionForm.expiry_mode === 'date' }" @click="redemptionForm.expiry_mode = 'date'">指定到期日期</button>
                    </div>
                    <input
                      v-if="redemptionForm.expiry_mode === 'days'"
                      v-model.number="redemptionForm.valid_days"
                      class="input"
                      type="number"
                      min="0"
                      step="1"
                      placeholder="0 表示永久有效"
                    />
                    <input v-else v-model="redemptionForm.expire_date" class="input" type="date" />
                    <p class="expiry-hint">{{ redemptionExpiryHint }}</p>
                  </div>
                </div>
                <!-- 【单用户使用限制】带边框分组卡片：左侧开关（关闭时右侧数字输入框置灰禁用），
                     右侧「最大使用次数」标签 + 数字输入框，底部一行简短提示。
                     绑定与原实现完全一致：开关关闭提交 per_user_max_times=0（沿用原有「按可用次数」逻辑），
                     开启后提交正整数 N，兑换时在 BEGIN IMMEDIATE 写锁内双重校验。 -->
                <section class="per-user-card">
                  <h3 class="per-user-card-title">单用户使用限制</h3>
                  <div class="per-user-card-body">
                    <label class="toggle-switch per-user-toggle">
                      <input v-model="redemptionForm.per_user_limit_enabled" type="checkbox" role="switch" />
                      <span class="toggle-track" aria-hidden="true"></span>
                      <span class="toggle-label">开启单用户次数限制</span>
                    </label>
                    <div class="per-user-limit-input">
                      <label for="redemption-per-user-max">最大使用次数</label>
                      <input
                        id="redemption-per-user-max"
                        v-model.number="redemptionForm.per_user_max_times"
                        class="input"
                        type="number"
                        min="1"
                        step="1"
                        :disabled="!redemptionForm.per_user_limit_enabled"
                        placeholder="请输入正整数"
                      />
                    </div>
                  </div>
                  <p class="per-user-card-hint">开启后，同一用户最多可使用该兑换码 {{ perUserMaxTimesHint }} 次。</p>
                </section>
                <div class="form-actions">
                  <button type="button" class="secondary-btn" @click="closeAddRedemptionModal">取消</button>
                  <button type="submit" class="primary-btn" :disabled="redemptionSaving">{{ redemptionSaving ? '保存中...' : '创建兑换码' }}</button>
                </div>
              </form>
            </div>
          </div>
        </div>

        <!-- 批量生成兑换码 -->
        <div v-if="showBatchRedemptionModal" class="modal-overlay" @click.self="closeBatchRedemptionModal">
          <div class="modal-content">
            <div class="modal-header">
              <h2>批量生成兑换码</h2>
              <button class="close-btn" @click="closeBatchRedemptionModal">×</button>
            </div>
            <div class="modal-body">
              <form @submit.prevent="saveBatchRedemption" class="add-printer-form">
                <div class="form-row">
                  <label>生成数量</label>
                  <input v-model.number="batchRedemptionForm.count" class="input" type="number" min="1" max="1000" step="1" />
                </div>
                <div class="form-row">
                  <label>单张面额（元）</label>
                  <input v-model.number="batchRedemptionForm.amount" class="input" type="number" min="0.01" step="0.01" required />
                </div>
                <div class="form-row">
                  <label>可用次数</label>
                  <input v-model.number="batchRedemptionForm.usable_count" class="input" type="number" min="1" step="1" />
                </div>
                <!-- 【新增功能】批量生成同样支持「按天数」/「指定到期日期」二选一，与手动新增一致。 -->
                <div class="form-row expiry-row">
                  <label>有效期</label>
                  <div class="expiry-control">
                    <div class="segmented expiry-mode">
                      <button type="button" :class="{ selected: batchRedemptionForm.expiry_mode === 'days' }" @click="batchRedemptionForm.expiry_mode = 'days'">按天数</button>
                      <button type="button" :class="{ selected: batchRedemptionForm.expiry_mode === 'date' }" @click="batchRedemptionForm.expiry_mode = 'date'">指定到期日期</button>
                    </div>
                    <input
                      v-if="batchRedemptionForm.expiry_mode === 'days'"
                      v-model.number="batchRedemptionForm.valid_days"
                      class="input"
                      type="number"
                      min="0"
                      step="1"
                      placeholder="0 表示永久有效"
                    />
                    <input v-else v-model="batchRedemptionForm.expire_date" class="input" type="date" />
                    <p class="expiry-hint">{{ batchRedemptionExpiryHint }}</p>
                  </div>
                </div>
                <div v-if="batchResult.length" class="batch-result">
                  <div class="batch-result-head"><strong>已生成 {{ batchResult.length }} 个兑换码</strong><button type="button" class="secondary-btn small" @click="copyBatchResult">复制全部</button></div>
                  <div class="batch-result-codes">
                    <span v-for="item in batchResult" :key="item.id" class="batch-code"><code>{{ item.code }}</code></span>
                  </div>
                </div>
                <div class="form-actions">
                  <button type="button" class="secondary-btn" @click="closeBatchRedemptionModal">取消</button>
                  <button type="submit" class="primary-btn" :disabled="batchRefreshing">{{ batchRefreshing ? '生成中...' : '立即生成' }}</button>
                </div>
              </form>
            </div>
          </div>
        </div>

        <!-- 兑换码详情（二级界面）：右侧抽屉，完整展示该兑换码的全部信息与已兑换用户列表 -->
        <div v-if="selectedRedemptionDetail" class="redemption-drawer-overlay" @click.self="closeRedemptionDetail">
          <aside class="redemption-drawer">
            <div class="redemption-drawer-header">
              <div>
                <p class="eyebrow">兑换码详情</p>
                <h2 class="redemption-drawer-code">{{ selectedRedemptionDetail.code }}</h2>
              </div>
              <button class="close-btn" @click="closeRedemptionDetail">×</button>
            </div>
            <div class="redemption-drawer-body">
              <div class="detail-grid redemption-detail-grid">
                <span>完整兑换码<strong class="redemption-code">{{ selectedRedemptionDetail.code }}</strong></span>
                <span>兑换面额<strong>¥{{ Number(selectedRedemptionDetail.amount).toFixed(2) }}</strong></span>
                <span>已兑换次数<strong>{{ selectedRedemptionDetail.used_count }} / {{ selectedRedemptionDetail.usable_count }}</strong></span>
                <span>生成时间<strong>{{ selectedRedemptionDetail.created_at ? formatDateTime(selectedRedemptionDetail.created_at) : '-' }}</strong></span>
                <!-- 【新增功能】有效期类型：date=管理员指定到期日期（此时天数列显示 —），days=按有效天数。 -->
                <span>有效期类型<strong>{{ selectedRedemptionDetail.expiry_mode === 'date' ? '指定到期日期' : '按有效天数' }}</strong></span>
                <span>有效天数<strong>{{ redemptionDetailValidDays(selectedRedemptionDetail) }}</strong></span>
                <span>精确到期<strong>{{ selectedRedemptionDetail.expires_at ? formatDateTime(selectedRedemptionDetail.expires_at) : '永久有效' }}</strong></span>
                <span>单用户使用上限<strong>{{ selectedRedemptionDetail.per_user_max_times > 0 ? `每人最多 ${selectedRedemptionDetail.per_user_max_times} 次` : '不限制' }}</strong></span>
                <span>使用状态<strong>{{ redemptionStatusLabel(selectedRedemptionDetail.status) }}</strong></span>
                <span>累计可兑金额<strong>¥{{ Number(selectedRedemptionDetail.total_amount || 0).toFixed(2) }}</strong></span>
              </div>

              <h3 class="redemption-drawer-subtitle">已兑换用户</h3>
              <div v-if="redemptionDetailLoading" class="empty-preview compact-empty">加载中...</div>
              <div v-else-if="redemptionLogs.length === 0" class="empty-preview compact-empty">暂无兑换记录</div>
              <div v-else class="redemption-log-list">
                <article v-for="log in redemptionLogs" :key="log.id" class="order-file-row">
                  <div>
                    <strong>{{ log.real_name || log.username || log.user_id || '未知用户' }}</strong>
                    <span>{{ formatDateTime(log.created_at) }}</span>
                  </div>
                  <strong>¥{{ Number(log.amount).toFixed(2) }}</strong>
                </article>
              </div>

              <div class="form-actions">
                <button type="button" class="primary-btn" @click="closeRedemptionDetail">关闭</button>
              </div>
            </div>
          </aside>
        </div>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Archive, CheckCircle, ClipboardList, Copy, CreditCard, DatabaseBackup, Download, ExternalLink, Eye, Globe, Gauge, MapPin, MoreHorizontal, Pencil, Plus, Power, Printer, RefreshCw, RotateCcw, Save, Search, Settings, Ticket, Trash2, UploadCloud, UserCog, XCircle } from 'lucide-vue-next'
import { buildApiUrl, request } from '../api/client'
import DailyStatsCard from '../components/DailyStatsCard.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

const tabs = [
  { key: 'dashboard', label: '概览', icon: Gauge },
  { key: 'orders', label: '订单', icon: ClipboardList },
  { key: 'users', label: '用户', icon: UserCog },
  { key: 'settings', label: '配置', icon: Settings },
  { key: 'payment', label: '支付', icon: CreditCard },
  { key: 'redemptions', label: '兑换码', icon: Ticket },
  { key: 'backups', label: '备份', icon: DatabaseBackup },
  { key: 'printers', label: '打印机', icon: Printer }
]
const tab = ref('dashboard')
// 手机端底部 Tab 栏：后台共 8 个 tab，窄屏底部放不下，因此常用 tab 常驻、其余收进「更多」面板。
// 桌面端不受影响，仍由 .admin-menu 展示全部 tab；两端共用同一个 tab 状态与 loadTab()，
// 所以切换行为与点击 .admin-menu 按钮完全一致（只改 tab ref，不涉及路由跳转）。
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

function showFeedback(message, type = 'success') {
  feedback.value = message
  feedbackType.value = type
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
    showFeedback('兑换码已复制到剪贴板')
  } catch {
    // 剪贴板 API 被禁用时回退到临时 textarea 选中复制。
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
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
  if (!window.confirm(`确认删除订单 ${order.id}？订单详情会删除，该订单独占的本地源文件/PDF缓存也会删除；被其他订单共用的文件会保留。`)) return
  await runAction(async () => {
    await request(`/api/admin/orders/${order.id}`, { method: 'DELETE' })
    if (selectedOrderDetail.value?.order?.id === order.id) closeOrderDetail()
    await loadTab()
  }, '订单已删除')
}

async function deleteUnpaidOrder(order) {
  if (!window.confirm(`确认删除未支付订单 ${order.id}？订单记录和该订单独占的文件缓存会删除。`)) return
  await runAction(async () => {
    await request(`/api/admin/orders/${order.id}/unpaid`, { method: 'DELETE' })
    if (selectedOrderDetail.value?.order?.id === order.id) closeOrderDetail()
    await loadTab()
  }, '未支付订单已删除')
}

async function deleteAllUnpaidOrders() {
  const count = unpaidOrdersCount.value
  if (!count) return
  if (!window.confirm(`确认删除全部 ${count} 个未支付订单？订单记录和这些订单独占的文件缓存会删除。`)) return
  await runAction(async () => {
    const result = await request('/api/admin/orders/unpaid/bulk', { method: 'DELETE' })
    if (result.deleted_order_ids?.includes(selectedOrderDetail.value?.order?.id)) closeOrderDetail()
    await loadTab()
  }, `已删除 ${count} 个未支付订单`)
}

async function loadOrderDetail(id) {
  await runAction(async () => {
    selectedOrderDetail.value = await request(`/api/admin/orders/${id}/detail`)
    selectedOrderFile.value = selectedOrderDetail.value.files.find((file) => file.preview_url) || null
  }, '订单详情已加载')
}

function closeOrderDetail() {
  selectedOrderDetail.value = null
  selectedOrderFile.value = null
}

function previewOrderFile(file) {
  selectedOrderFile.value = file
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
      selectedOrderFile.value = selectedOrderDetail.value.files.find((file) => file.preview_url) || null
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
