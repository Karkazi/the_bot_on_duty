# Простая инструкция: Создание API для комментариев в SimpleOne

> **Примечание:** В текущей версии бота сообщения о закрытии сбоев и работ публикуются на Петлокале **отдельными постами**, а не комментариями к исходному посту. Scripted REST API для комментариев ботом не используется. Инструкция сохранена для справки.

## 🎯 Зачем это нужно?

Когда бот создает пост на портале Petlocal, он получает **числовой ID** (например: `176974959802799179`).  
Но для добавления комментария нужен **UUID** (например: `026bd370-...`).

**Решение:** Создать специальный API в SimpleOne, который сам найдет нужный UUID и добавит комментарий.

---

## 📋 Что нужно перед началом

**Важно:** Для создания Scripted REST API нужны специальные права в SimpleOne.

### Если у вас есть права администратора:
- ✅ Можете создать API самостоятельно
- ✅ Следуйте инструкции ниже

### Если у вас нет прав администратора:
- ⚠️ Нужна помощь администратора SimpleOne
- 📝 Покажите ему эту инструкцию
- 💬 Или попросите создать API с такими параметрами:
  - **API ID**: `petlocal_comments`
  - **Resource**: `add_comment` (метод POST, путь `/add_comment`)
  - **Код скрипта**: (см. Шаг 4 ниже)

**Минимальные требования:**
- Доступ к SimpleOne
- Права на создание Scripted REST APIs (обычно требуют роль `admin` или `itil_admin`)
- Знание, где находится ваш портал Petlocal
- 10-15 минут времени

---

## 🚀 Пошаговая инструкция

### Шаг 1: Открыть раздел Scripted REST APIs

**⚠️ Внимание:** Если у вас нет прав администратора, попросите администратора выполнить шаги 1-4.

1. Войдите в SimpleOne (нужны права администратора или `itil_admin`)
2. В левом меню найдите **System Definition** (Системное определение)
3. В выпадающем списке выберите **Scripted REST APIs**
4. Вы увидите список существующих API (если есть)

**Если у вас нет доступа:**
- Обратитесь к администратору SimpleOne
- Попросите его создать API по этой инструкции
- Или используйте fallback метод (см. раздел "Альтернатива без API" ниже)

### Шаг 2: Создать новый API

1. Нажмите кнопку **New** (Создать) вверху страницы
2. Заполните поля:
   - **Name**: `petlocal_comments` (любое название, но лучше использовать это)
   - **API ID**: `petlocal_comments` (должно совпадать с Name)
   - **Description**: `API для добавления комментариев на портал Petlocal`
3. Нажмите **Submit** (Сохранить)

✅ **Готово!** API создан. Теперь нужно добавить в него функцию.

### Шаг 3: Добавить функцию добавления комментария

1. В созданном API найдите раздел **Resources** (Ресурсы)
2. Нажмите **New** (Создать) в этом разделе
3. Заполните поля:
   - **Name**: `add_comment`
   - **HTTP method**: Выберите `POST` из списка
   - **Relative path**: `/add_comment`
   - **Description**: `Добавляет комментарий к посту по его ID`
4. Прокрутите вниз до поля **Script** (Скрипт)

### Шаг 4: Вставить код

1. Скопируйте весь код ниже (от `(function` до `})(request, response);`)
2. Вставьте его в поле **Script**
3. Нажмите **Submit** (Сохранить)

```javascript
(function process(/*RESTAPIRequest*/ request, /*RESTAPIResponse*/ response) {
    try {
        // Получаем данные из запроса
        var requestBody = request.body.data;
        var postSysId = requestBody.post_sys_id;
        var commentText = requestBody.comment_text;
        
        // Проверяем, что все данные есть
        if (!postSysId || !commentText) {
            response.setStatus(400);
            response.setBody({
                "success": false,
                "error": "post_sys_id и comment_text обязательны"
            });
            return;
        }
        
        // Ищем пост в базе данных
        var postGr = new GlideRecord('c_portal_news');
        if (!postGr.get(postSysId)) {
            response.setStatus(404);
            response.setBody({
                "success": false,
                "error": "Пост с указанным sys_id не найден"
            });
            return;
        }
        
        // Получаем UUID поста
        var objectId = postGr.getValue('object_id');
        if (!objectId) {
            objectId = postGr.getUniqueValue();
        }
        
        // Создаем комментарий
        var commentGr = new GlideRecord('c_portal_comment');
        commentGr.initialize();
        commentGr.setValue('active', true);
        commentGr.setValue('object_id', objectId);
        commentGr.setValue('text', commentText);
        var commentSysId = commentGr.insert();
        
        // Проверяем, что комментарий создан
        if (!commentSysId) {
            response.setStatus(500);
            response.setBody({
                "success": false,
                "error": "Не удалось создать комментарий"
            });
            return;
        }
        
        // Возвращаем успешный результат
        response.setStatus(200);
        response.setBody({
            "success": true,
            "data": {
                "comment_sys_id": commentSysId,
                "object_id": objectId,
                "post_sys_id": postSysId
            }
        });
        
    } catch (e) {
        response.setStatus(500);
        response.setBody({
            "success": false,
            "error": "Внутренняя ошибка: " + e.toString()
        });
    }
})(request, response);
```

✅ **Готово!** Функция добавлена. Теперь нужно узнать адрес API.

### Шаг 5: Узнать адрес вашего API

1. Вернитесь к списку Scripted REST APIs
2. Найдите созданный API `petlocal_comments`
3. Откройте его
4. Посмотрите на **API ID** - это будет часть адреса
5. Найдите **Scope** (Область) - это может быть `sn_customerservice`, `x_12345` или что-то подобное

**Адрес API будет таким:**
```
https://test-petrovich.simpleone.ru/api/x_<scope>/petlocal_comments/add_comment
```

**Пример:**
- Если scope = `sn_customerservice`, то адрес:
  ```
  https://test-petrovich.simpleone.ru/api/x_sn_customerservice/petlocal_comments/add_comment
  ```

### Шаг 6: Настроить бота

1. Откройте файл `.env` в корне проекта
2. Добавьте одну из строк (замените `<scope>` на ваш scope):

**Вариант 1: Полный путь (рекомендуется)**
```env
SIMPLEONE_COMMENTS_API_PATH=/api/x_sn_customerservice/petlocal_comments/add_comment
```

**Вариант 2: Только scope (проще)**
```env
SIMPLEONE_COMMENTS_API_SCOPE=sn_customerservice
```

3. Сохраните файл `.env`
4. Перезапустите бота

✅ **Готово!** Теперь бот будет использовать ваш API.

---

## 🧪 Как проверить, что всё работает?

### Способ 1: Через тестовый скрипт (проще всего)

1. Запустите команду:
   ```bash
   python tests/test_add_comment_to_post.py
   ```

2. Скрипт автоматически:
   - Проверит настройки
   - Отправит тестовый комментарий к вашему посту
   - Покажет результат

### Способ 2: Вручную через curl

Замените `<scope>` и `<token>` на ваши значения:

```bash
curl -X POST "https://test-petrovich.simpleone.ru/api/x_<scope>/petlocal_comments/add_comment" \
  -H "Authorization: Bearer <ваш_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "post_sys_id": "176974959802799179",
    "comment_text": "✅ Тестовый комментарий"
  }'
```

### Способ 3: Проверить на портале

1. Откройте портал Petlocal:
   ```
   https://test-petrovich.simpleone.ru/petlocal/?post_group_id=176251796307142895
   ```

2. Найдите пост с ID `176974959802799179`
3. Проверьте, появился ли комментарий

---

## ❓ Частые вопросы

### Как узнать scope моего приложения?

1. В SimpleOne перейдите в **System Definition → Applications**
2. Найдите ваше приложение (или создайте новое)
3. Scope будет указан в поле **Scope** или **Application ID**

### Что делать, если API не работает?

1. **Проверьте права доступа:**
   - Убедитесь, что у пользователя API есть права на создание комментариев
   - Перейдите в **System Security → Access Control (ACL)**
   - Создайте правило для таблицы `c_portal_comment`

2. **Проверьте адрес API:**
   - Убедитесь, что scope указан правильно
   - Проверьте, что путь `/add_comment` совпадает с Relative path

3. **Проверьте токен:**
   - Убедитесь, что `SIMPLEONE_TOKEN` в `.env` правильный
   - Токен должен иметь права на использование REST API

### Можно ли обойтись без Scripted REST API?

Да, можно! Бот умеет работать и без него (fallback метод). Но Scripted REST API:
- ✅ Надежнее
- ✅ Безопаснее
- ✅ Проще в использовании

### У меня нет прав администратора. Что делать?

**Вариант 1: Попросите администратора создать API** (рекомендуется)
- Покажите администратору эту инструкцию
- Попросите создать API с такими параметрами:
  - **API ID**: `petlocal_comments`
  - **Resource Name**: `add_comment`
  - **HTTP method**: `POST`
  - **Relative path**: `/add_comment`
  - **Script**: (код из Шага 4 выше)
- После создания вам нужно будет только добавить настройки в `.env`

**Вариант 2: Используйте fallback метод** (работает без API)
- Бот автоматически будет использовать fallback метод
- Просто **не указывайте** `SIMPLEONE_COMMENTS_API_PATH` или `SIMPLEONE_COMMENTS_API_SCOPE` в `.env`
- Бот сам получит `object_id` из поста и создаст комментарий
- Работает, но менее надежно, чем Scripted REST API

**Вариант 3: Попросите временные права**
- Обратитесь к администратору SimpleOne
- Попросите временные права на создание Scripted REST APIs
- После создания API права можно вернуть

---

## 📝 Краткая памятка

1. ✅ Создать Scripted REST API с ID `petlocal_comments`
2. ✅ Добавить Resource `add_comment` (метод POST)
3. ✅ Вставить код скрипта
4. ✅ Узнать scope приложения
5. ✅ Добавить в `.env` путь или scope
6. ✅ Протестировать через скрипт

---

## 🎉 Готово!

После выполнения всех шагов бот сможет автоматически добавлять комментарии к постам на Petlocal при закрытии сбоев и работ.

**Нужна помощь?** Проверьте логи бота или запустите тестовый скрипт для диагностики.
