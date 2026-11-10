<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { formatDateTime } from '@/i18n'
import { Badge } from '@/components/ui/badge'
import { listAccounts, getAccount, createAccount, updateAccount, deleteAccount, type AccountItem } from '@/api/accounts'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { toast } from '@/components/ui/toast'
const { t } = useI18n()

const accounts = ref<AccountItem[]>([])
const isLoading = ref(false)
const isSaving = ref(false)
const router = useRouter()

const isEditDialogOpen = ref(false)
const isDeleteDialogOpen = ref(false)

const editName = ref('')
const editContent = ref('')
const deleteName = ref('')

// 快速貼上：預設存成 shopee，同名時直接覆蓋，方便 Cookie 過期後重貼
const quickName = ref('shopee')
const quickContent = ref('')

async function handleQuickSave() {
  if (!quickContent.value.trim()) {
    toast({ title: t('accounts.toasts.contentRequired'), description: t('accounts.toasts.updateDescriptionRequired'), variant: 'destructive' })
    return
  }
  isSaving.value = true
  try {
    const saved = await createAccount({
      name: quickName.value.trim() || 'shopee',
      content: quickContent.value.trim(),
      overwrite: true,
    })
    quickContent.value = ''
    if (saved.logged_in) {
      toast({ title: t('accounts.quick.saved', { name: saved.name }) })
    } else {
      toast({ title: t('accounts.quick.savedNotLoggedIn'), description: t('accounts.quick.notLoggedInHint'), variant: 'destructive' })
    }
    await fetchAccounts()
  } catch (e) {
    toast({ title: t('accounts.toasts.createFailed'), description: (e as Error).message, variant: 'destructive' })
  } finally {
    isSaving.value = false
  }
}

function statusLabel(account: AccountItem) {
  if (account.invalid) return t('accounts.status.invalid')
  if (account.expired) return t('accounts.status.expired')
  return account.logged_in ? t('accounts.status.loggedIn') : t('accounts.status.notLoggedIn')
}

function isHealthy(account: AccountItem) {
  return !!account.logged_in && !account.expired && !account.invalid
}

function formatTime(value?: string | null) {
  return value ? formatDateTime(value, { dateStyle: 'medium', timeStyle: 'short' }) : '—'
}

async function fetchAccounts() {
  isLoading.value = true
  try {
    accounts.value = await listAccounts()
  } catch (e) {
    toast({ title: t('accounts.toasts.loadFailed'), description: (e as Error).message, variant: 'destructive' })
  } finally {
    isLoading.value = false
  }
}

async function openEditDialog(name: string) {
  isSaving.value = true
  try {
    const detail = await getAccount(name)
    editName.value = detail.name
    editContent.value = detail.content
    isEditDialogOpen.value = true
  } catch (e) {
    toast({ title: t('accounts.toasts.loadContentFailed'), description: (e as Error).message, variant: 'destructive' })
  } finally {
    isSaving.value = false
  }
}

function openDeleteDialog(name: string) {
  deleteName.value = name
  isDeleteDialogOpen.value = true
}

function goCreateTask(name: string) {
  router.push({ path: '/tasks', query: { account: name, create: '1' } })
}

async function handleUpdateAccount() {
  if (!editContent.value.trim()) {
    toast({ title: t('accounts.toasts.contentRequired'), description: t('accounts.toasts.updateDescriptionRequired'), variant: 'destructive' })
    return
  }
  isSaving.value = true
  try {
    await updateAccount(editName.value, editContent.value.trim())
    toast({ title: t('accounts.toasts.updated') })
    isEditDialogOpen.value = false
    await fetchAccounts()
  } catch (e) {
    toast({ title: t('accounts.toasts.updateFailed'), description: (e as Error).message, variant: 'destructive' })
  } finally {
    isSaving.value = false
  }
}

async function handleDeleteAccount() {
  isSaving.value = true
  try {
    await deleteAccount(deleteName.value)
    toast({ title: t('accounts.toasts.deleted') })
    isDeleteDialogOpen.value = false
    await fetchAccounts()
  } catch (e) {
    toast({ title: t('accounts.toasts.deleteFailed'), description: (e as Error).message, variant: 'destructive' })
  } finally {
    isSaving.value = false
  }
}

onMounted(fetchAccounts)
</script>

<template>
  <div>
    <div class="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold text-gray-800">{{ t('accounts.title') }}</h1>
        <p class="text-sm text-gray-500 mt-1">{{ t('accounts.description') }}</p>
      </div>
    </div>

    <Card class="app-surface mb-6 border-none">
      <CardHeader>
        <CardTitle>{{ t('accounts.quick.title') }}</CardTitle>
        <CardDescription>{{ t('accounts.quick.description') }}</CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <Textarea v-model="quickContent" class="min-h-[140px] font-mono text-xs" :placeholder="t('accounts.createDialog.jsonPlaceholder')" />
        <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div class="grid gap-2 sm:w-64">
            <Label>{{ t('accounts.createDialog.name') }}</Label>
            <Input v-model="quickName" placeholder="shopee" />
          </div>
          <Button class="sm:w-auto" :disabled="isSaving" @click="handleQuickSave">
            {{ isSaving ? t('common.saving') : t('accounts.quick.save') }}
          </Button>
        </div>
      </CardContent>
    </Card>

    <Card class="app-surface mb-6 border-none">
      <CardHeader>
        <CardTitle>{{ t('accounts.cookieGuide.title') }}</CardTitle>
      </CardHeader>
      <CardContent class="text-sm text-gray-600">
        <ol class="list-decimal list-inside space-y-1">
          <li>
            {{ t('accounts.cookieGuide.step1Prefix') }}
            <a
              class="text-blue-600 hover:underline"
              href="https://developer.chrome.com/docs/extensions/get-started/tutorial/hello-world#load-unpacked"
              target="_blank"
              rel="noopener noreferrer"
            >{{ t('accounts.cookieGuide.extension') }}</a>
          </li>
          <li>
            {{ t('accounts.cookieGuide.step2Prefix') }}
            <a
              class="text-blue-600 hover:underline"
              href="https://shopee.tw"
              target="_blank"
              rel="noopener noreferrer"
            >{{ t('accounts.cookieGuide.website') }}</a>
          </li>
          <li>{{ t('accounts.cookieGuide.step3') }}</li>
          <li>{{ t('accounts.cookieGuide.step4') }}</li>
          <li>{{ t('accounts.cookieGuide.step5') }}</li>
        </ol>
      </CardContent>
    </Card>

    <Card class="app-surface border-none">
      <CardHeader>
        <CardTitle>{{ t('accounts.list.title') }}</CardTitle>
        <CardDescription>{{ t('accounts.list.description') }}</CardDescription>
      </CardHeader>
      <CardContent>
        <div class="space-y-4 md:hidden">
          <div v-if="isLoading" class="py-10 text-center text-sm text-muted-foreground">{{ t('common.loading') }}</div>
          <div v-else-if="accounts.length === 0" class="py-10 text-center text-sm text-muted-foreground">{{ t('accounts.list.empty') }}</div>
          <article
            v-else
            v-for="account in accounts"
            :key="account.name"
            class="app-surface-subtle p-4"
          >
            <div class="space-y-2">
              <div class="flex items-center justify-between gap-3">
                <h3 class="truncate text-base font-semibold text-slate-900">{{ account.name }}</h3>
                <Button size="sm" variant="outline" @click="goCreateTask(account.name)">{{ t('accounts.list.createTask') }}</Button>
              </div>
              <div class="flex flex-wrap items-center gap-2 text-sm text-slate-500">
                <Badge :variant="isHealthy(account) ? 'default' : 'destructive'">{{ statusLabel(account) }}</Badge>
                <span v-if="account.shopee_user_id">ID {{ account.shopee_user_id }}</span>
                <span>{{ t('accounts.status.updatedAt', { time: formatTime(account.updated_at) }) }}</span>
              </div>
            </div>
            <div class="mt-4 flex flex-wrap gap-2">
              <Button size="sm" variant="outline" class="flex-1 min-w-[120px]" @click="openEditDialog(account.name)">{{ t('accounts.list.update') }}</Button>
              <Button size="sm" variant="destructive" class="flex-1 min-w-[120px]" @click="openDeleteDialog(account.name)">{{ t('accounts.list.delete') }}</Button>
            </div>
          </article>
        </div>

        <div class="hidden md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{{ t('accounts.list.name') }}</TableHead>
                <TableHead>{{ t('accounts.status.title') }}</TableHead>
                <TableHead>{{ t('accounts.status.expiresAt') }}</TableHead>
                <TableHead>{{ t('accounts.status.updated') }}</TableHead>
                <TableHead class="text-right">{{ t('accounts.list.actions') }}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-if="isLoading">
                <TableCell colspan="5" class="h-20 text-center text-muted-foreground">{{ t('common.loading') }}</TableCell>
              </TableRow>
              <TableRow v-else-if="accounts.length === 0">
                <TableCell colspan="5" class="h-20 text-center text-muted-foreground">{{ t('accounts.list.empty') }}</TableCell>
              </TableRow>
              <TableRow v-else v-for="account in accounts" :key="account.name">
                <TableCell class="font-medium">{{ account.name }}</TableCell>
                <TableCell>
                  <div class="flex flex-wrap items-center gap-2 text-sm text-gray-500">
                    <Badge :variant="isHealthy(account) ? 'default' : 'destructive'">{{ statusLabel(account) }}</Badge>
                    <span v-if="account.shopee_user_id">ID {{ account.shopee_user_id }}</span>
                    <span>{{ t('accounts.status.cookieCount', { count: account.cookie_count ?? 0 }) }}</span>
                  </div>
                </TableCell>
                <TableCell class="text-sm text-gray-500">{{ formatTime(account.expires_at) }}</TableCell>
                <TableCell class="text-sm text-gray-500">{{ formatTime(account.updated_at) }}</TableCell>
                <TableCell class="text-right">
                  <div class="flex justify-end gap-2">
                    <Button size="sm" variant="outline" @click="goCreateTask(account.name)">{{ t('accounts.list.createTask') }}</Button>
                    <Button size="sm" variant="outline" @click="openEditDialog(account.name)">{{ t('accounts.list.update') }}</Button>
                    <Button size="sm" variant="destructive" @click="openDeleteDialog(account.name)">{{ t('accounts.list.delete') }}</Button>
                  </div>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>

    <Dialog v-model:open="isEditDialogOpen">
      <DialogContent class="sm:max-w-[700px]">
        <DialogHeader>
          <DialogTitle>{{ t('accounts.editDialog.title', { name: editName }) }}</DialogTitle>
          <DialogDescription>{{ t('accounts.editDialog.description') }}</DialogDescription>
        </DialogHeader>
        <div class="space-y-4">
          <div class="grid gap-2">
            <Label>{{ t('accounts.createDialog.jsonContent') }}</Label>
            <Textarea v-model="editContent" class="min-h-[200px]" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="isEditDialogOpen = false">{{ t('common.cancel') }}</Button>
          <Button :disabled="isSaving" @click="handleUpdateAccount">
            {{ isSaving ? t('common.saving') : t('common.save') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="isDeleteDialogOpen">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{{ t('accounts.deleteDialog.title') }}</DialogTitle>
          <DialogDescription>{{ t('accounts.deleteDialog.description', { name: deleteName }) }}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="isDeleteDialogOpen = false">{{ t('common.cancel') }}</Button>
          <Button variant="destructive" :disabled="isSaving" @click="handleDeleteAccount">
            {{ isSaving ? t('accounts.deleteDialog.deleting') : t('accounts.list.delete') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
