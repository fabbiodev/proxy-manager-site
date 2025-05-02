document.addEventListener('DOMContentLoaded', () => {
  // Копирование по иконке
  document.querySelectorAll('.copy-icon').forEach(icon => {
    icon.addEventListener('click', () => {
      const txt = icon.dataset.text;
      navigator.clipboard.writeText(txt)
        .then(() => {
          icon.style.opacity = '0.5';
          setTimeout(() => icon.style.opacity = '1', 500);
        });
    });
  });

  // Анимация прогресс-бара
  const form = document.getElementById('getProxyForm');
  if (form) {
    const progressContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    form.addEventListener('submit', e => {
      e.preventDefault();
      progressContainer.style.display = 'block';
      setTimeout(() => { progressBar.style.width = '100%'; }, 10);
      setTimeout(() => { form.submit(); }, 3000);
    });
  }

  // Изменение текста лейбла при выборе файла
  const fileInput = document.getElementById('fileInput');
  if (fileInput) {
    const fileLabel = document.getElementById('file-label');
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length > 0) {
        const name = fileInput.files[0].name;
        fileLabel.textContent = `Выбран ${name} для загрузки`;
      } else {
        fileLabel.textContent = 'Выберите .txt файл';
      }
    });
  }

  // Валидация форм (если осталась)
  document.querySelectorAll('form[novalidate]').forEach(form => {
    form.addEventListener('submit', e => {
      let ok = true;
      form.querySelectorAll('input[required], textarea[required]').forEach(f => {
        if (!f.value.trim()) {
          ok = false;
          f.style.border = '1px solid #FF453A';
        }
      });
      if (!ok) e.preventDefault();
    });
    form.querySelectorAll('input, textarea').forEach(f => {
      f.addEventListener('input', () => f.style.border = '');
    });
  });
});
