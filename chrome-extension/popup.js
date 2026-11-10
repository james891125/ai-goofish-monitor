// Popup script for the Chrome extension
document.addEventListener('DOMContentLoaded', function() {
  const extractBtn = document.getElementById('extractBtn');
  const copyBtn = document.getElementById('copyBtn');
  const stateOutput = document.getElementById('stateOutput');
  const statusDiv = document.getElementById('status');

  let latestSnapshot = null;

  function setLoading(isLoading) {
    extractBtn.disabled = isLoading;
    extractBtn.textContent = isLoading ? '採集中，請稍候...' : '1.點選獲取環境+登入狀態';
  }

  function updateStatus(message, isSuccess = false) {
    statusDiv.textContent = message;
    statusDiv.className = 'status ' + (isSuccess ? 'success' : 'error');
    setTimeout(() => {
      statusDiv.textContent = '';
      statusDiv.className = 'status';
    }, 4000);
  }

  function renderSnapshot(snapshot) {
    latestSnapshot = snapshot;
    stateOutput.value = JSON.stringify(snapshot, null, 2);
  }

  async function captureSnapshot() {
    setLoading(true);
    updateStatus('正在採集瀏覽器環境與登入狀態...');
    stateOutput.value = '';

    chrome.runtime.sendMessage({ type: 'captureSnapshot' }, (response) => {
      setLoading(false);

      if (chrome.runtime.lastError) {
        updateStatus('通訊失敗: ' + chrome.runtime.lastError.message);
        return;
      }
      if (!response || !response.ok) {
        updateStatus('採集失敗: ' + (response?.error || '未知錯誤'));
        return;
      }

      renderSnapshot(response.data);
      updateStatus('採集完成，已生成JSON', true);
    });
  }

  function copySnapshot() {
    if (!stateOutput.value) {
      updateStatus('沒有可複製的資料');
      return;
    }
    navigator.clipboard.writeText(stateOutput.value)
      .then(() => updateStatus('已複製到剪貼簿', true))
      .catch(err => updateStatus('複製失敗: ' + err));
  }

  extractBtn.addEventListener('click', captureSnapshot);
  copyBtn.addEventListener('click', copySnapshot);
});
