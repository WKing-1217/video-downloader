#include "Controller.h"
#include <QClipboard>
#include <QGuiApplication>
#include <QJsonDocument>
#include <QJsonArray>
#include <QRegularExpression>
#include <QTimer>
#include <QUrl>
#include <QUrlQuery>
#include <QDesktopServices>
#include <QSettings>
#include <QList>
#include <QStringList>
#include <algorithm>
#ifdef Q_OS_ANDROID
#include <QJniObject>
#endif

static constexpr auto bridge = "com/localvideodownloader/app/DownloadBridge";
static QString clockText(double seconds) {
    int s = qRound(seconds);
    return QString("%1:%2").arg(s / 60, 2, 10, QChar('0')).arg(s % 60, 2, 10, QChar('0'));
}
static QSettings settings() { return QSettings("LocalVideoDownloader", "VideoDownloader"); }

Controller::Controller(QObject *parent) : QObject(parent) {
#ifdef Q_OS_ANDROID
    auto timer = new QTimer(this);
    connect(timer, &QTimer::timeout, this, [this] {
        const auto text = QJniObject::callStaticObjectMethod(bridge, "takeSharedText", "()Ljava/lang/String;").toString();
        if (!text.isEmpty()) { setPage(0); setLink(text); }
        const auto events = QJniObject::callStaticObjectMethod(bridge, "takeEvents", "()Ljava/lang/String;").toString();
        for (const auto &line : events.split('\n', Qt::SkipEmptyParts)) consume(line);
        startNext();
    });
    timer->start(150);
    QTimer::singleShot(300, this, &Controller::refreshLibrary);
    if (autoUpdate()) QTimer::singleShot(2500, this, [this] { checkForUpdates(false); });
#endif
}
void Controller::setPage(int value) {
    if (value < 0 || value > 3 || m_page == value) return;
    m_page = value; if(value==3)refreshLibrary(); emit changed();
}
QString Controller::version() const { return QStringLiteral(APP_VERSION); }
bool Controller::autoUpdate() const { return settings().value("autoUpdate", true).toBool(); }
void Controller::setAutoUpdate(bool enabled) { settings().setValue("autoUpdate", enabled); emit changed(); }
QString Controller::videoFormat() const {
    const auto value = settings().value("videoFormat", "mp4").toString();
    return QStringList{"mp4", "mkv", "mov", "webm"}.contains(value) ? value : "mp4";
}
QString Controller::imageFormat() const {
    const auto value = settings().value("imageFormat", "png").toString();
    return QStringList{"png", "jpg", "webp"}.contains(value) ? value : "png";
}
int Controller::audioBitrate() const {
    const auto value = settings().value("audioBitrate", 192).toInt();
    return QList<int>{128, 192, 256, 320}.contains(value) ? value : 192;
}
void Controller::setVideoFormat(const QString &value) {
    if (QStringList{"mp4", "mkv", "mov", "webm"}.contains(value)) { settings().setValue("videoFormat", value); emit changed(); }
}
void Controller::setImageFormat(const QString &value) {
    if (QStringList{"png", "jpg", "webp"}.contains(value)) { settings().setValue("imageFormat", value); emit changed(); }
}
void Controller::setAudioBitrate(int value) {
    if (QList<int>{128, 192, 256, 320}.contains(value)) { settings().setValue("audioBitrate", value); emit changed(); }
}
bool Controller::canExtractLast() const {
    return !m_video.result.isEmpty() && (m_video.result["kind"] == "video" || m_video.result["content_type"] == "video"
                                        || m_video.result["width"].toInt() > 0);
}
void Controller::checkForUpdates(bool manual) {
    if (manual) { m_updateStatus = "正在检查更新…"; emit changed(); }
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(bridge, "checkForUpdates", "(Z)V", manual);
#endif
}
void Controller::openUpdate() {
    if (m_updateAvailable && !m_updateUrl.isEmpty()) QDesktopServices::openUrl(QUrl(m_updateUrl));
}
static QString supportedPlatform(const QUrl &url) {
    if (!url.isValid() || !url.userInfo().isEmpty() || url.port() != -1) return {};
    const auto host = url.host().toLower();
    auto path = url.path();
    while (path.endsWith('/')) path.chop(1);
    auto matches = [&path](const QString &pattern) { return QRegularExpression(pattern).match(path).hasMatch(); };
    if (host == "b23.tv") return matches("^/[A-Za-z0-9_-]{3,}$") ? "Bilibili" : QString();
    if (QStringList{"bilibili.com", "www.bilibili.com", "m.bilibili.com"}.contains(host))
        return matches("^/(?:video/(?:BV[0-9A-Za-z]+|av[0-9]+)|bangumi/play/(?:ep|ss)[0-9]+)$") ? "Bilibili" : QString();
    if (host == "v.douyin.com") return matches("^/[A-Za-z0-9_-]{3,}$") ? "抖音" : QString();
    if (QStringList{"douyin.com", "www.douyin.com", "m.douyin.com", "iesdouyin.com", "www.iesdouyin.com"}.contains(host)) {
        const QUrlQuery query(url);
        const auto selected = query.queryItemValue("modal_id").isEmpty() ? query.queryItemValue("vid") : query.queryItemValue("modal_id");
        return matches("^/(?:share/)?(?:video|note|slides)/[0-9]+$") || QRegularExpression("^[0-9]+$").match(selected).hasMatch() ? "抖音" : QString();
    }
    if (host == "t.co") return matches("^/[A-Za-z0-9_-]{3,}$") ? "X" : QString();
    if (QStringList{"x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com", "m.twitter.com"}.contains(host))
        return matches("^/[^/]+/status/[0-9]+(?:/video/[0-9]+)?$") ? "X" : QString();
    if (QStringList{"instagram.com", "www.instagram.com", "m.instagram.com"}.contains(host))
        return matches("^/(?:reel|reels|p|tv)/[A-Za-z0-9_-]+$") ? "Instagram" : QString();
    if (host == "youtu.be") return matches("^/[A-Za-z0-9_-]{11}$") ? "YouTube" : QString();
    if (QStringList{"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}.contains(host)) {
        const auto ids = QUrlQuery(url).allQueryItemValues("v");
        return (path == "/watch" && ids.size() == 1 && QRegularExpression("^[A-Za-z0-9_-]{11}$").match(ids.first()).hasMatch())
            || matches("^/(?:shorts|embed|live)/[A-Za-z0-9_-]{11}$") ? "YouTube" : QString();
    }
    return {};
}
void Controller::setLink(const QString &text) {
    auto &state = current();
    state.link = text; state.platform.clear();
    QRegularExpression urls("https?://[^\\s<>\"“”。；！？]+", QRegularExpression::CaseInsensitiveOption);
    auto matches = urls.globalMatch(text);
    while (matches.hasNext()) {
        auto candidate = matches.next().captured();
        while (!candidate.isEmpty() && QString(",）)]};;、。").contains(candidate.back())) candidate.chop(1);
        const QUrl url(candidate);
        state.platform = supportedPlatform(url);
        if (!state.platform.isEmpty()) break;
    }
    emit changed();
}
void Controller::paste() { setLink(QGuiApplication::clipboard()->text()); }
static QString queueIdentity(const QString &text) {
    QRegularExpression links("https?://[^\\s<>\"“”。；！？]+", QRegularExpression::CaseInsensitiveOption);
    auto matches = links.globalMatch(text);
    while (matches.hasNext()) {
        auto candidate = matches.next().captured();
        while (!candidate.isEmpty() && QString(",）)]};;、。").contains(candidate.back())) candidate.chop(1);
        QUrl url(candidate);
        const QString site = supportedPlatform(url);
        if (site.isEmpty()) continue;
        QString path = url.path();
        while (path.endsWith('/')) path.chop(1);
        QUrlQuery query(url), selected;
        QString host = url.host().toLower();
        if (site == "YouTube") {
            const QString id = path == "/watch" ? query.queryItemValue("v") : path.section('/', -1);
            return "youtube:" + id;
        }
        if (site == "Instagram") return "instagram:" + path.section('/', -1);
        if (site == "抖音") {
            QString id = query.queryItemValue("modal_id");
            if (id.isEmpty()) id = query.queryItemValue("vid");
            if (!id.isEmpty()) return "douyin:" + id;
            if (host != "v.douyin.com") return "douyin:" + path.section('/', -1);
        }
        if (site == "Bilibili") {
            if (host != "b23.tv") host = "www.bilibili.com";
            const auto part = query.queryItemValue("p");
            if (QRegularExpression("^[0-9]+$").match(part).hasMatch()) selected.addQueryItem("p", part);
        }
        if (site == "X" && host != "t.co") host = "x.com";
        url.setScheme("https"); url.setHost(host); url.setPath(path); url.setQuery(selected); url.setFragment({});
        return url.toString();
    }
    return text.trimmed();
}
int Controller::queuedCount() const {
    int count = 0;
    for (const auto &task : m_queue) if (task.mode == currentMode()) ++count;
    return count;
}
void Controller::clearQueue() {
    const auto mode = currentMode();
    for (int i = m_queue.size() - 1; i >= 0; --i) if (m_queue.at(i).mode == mode) m_queue.removeAt(i);
    currentQueueStatus().clear(); emit changed();
}
bool Controller::nativeWorkerRunning() const {
#ifdef Q_OS_ANDROID
    return QJniObject::callStaticMethod<jboolean>("com/localvideodownloader/app/DownloadService", "isRunning", "()Z");
#else
    return false;
#endif
}
void Controller::startNext() {
    if (m_busy || m_pickerPending || m_storageBusy || m_queue.isEmpty() || nativeWorkerRunning()) return;
    m_activeKey.clear();
    startPending(m_queue.dequeue());
}
void Controller::start() {
    if (m_pickerPending || m_storageBusy) return;
    auto &state = current();
    const auto mode = currentMode();
    if (state.platform.isEmpty()) {
        if (m_busy) {
            currentQueueStatus() = "请粘贴支持平台的单条作品链接。";
            emit changed(); return;
        }
        state.hasTask = true; state.title = "未能开始";
        state.result = {}; state.progress = 0; state.details.clear();
        state.status = "请粘贴支持平台的单条作品链接。";
        emit changed(); return;
    }
    PendingDownload task{state.link, state.platform, mode, videoFormat(), imageFormat(), {}, audioBitrate()};
    task.key = queueIdentity(task.link) + "|" + mode + "|" + task.videoFormat + "|" + task.imageFormat + "|" + QString::number(task.audioBitrate);
    const bool duplicate = (!m_activeKey.isEmpty() && (m_busy || nativeWorkerRunning()) && m_activeKey == task.key)
        || std::any_of(m_queue.cbegin(), m_queue.cend(), [&task](const auto &pending) { return pending.key == task.key; });
    if (duplicate) { currentQueueStatus() = "这个链接已在任务中。"; emit changed(); return; }
    if (m_queue.size() >= 64) { currentQueueStatus() = "等待任务较多，请完成后再添加。"; emit changed(); return; }
    currentQueueStatus().clear();
    if (m_busy || nativeWorkerRunning() || !m_queue.isEmpty()) {
        m_queue.enqueue(task);
        emit changed();
        startNext();
        return;
    }
    startPending(task);
}
void Controller::startPending(const PendingDownload &task) {
    auto &state = forMode(task.mode);
    m_busy = true; m_activeMode = task.mode; m_activeKey = task.key;
    state.progress = -1; state.result = {}; state.logs.clear(); state.hasTask = true;
    state.title = "正在读取作品信息"; state.status = "正在连接 " + task.platform + "…";
    state.details.clear();
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(bridge, "start", "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;I)V",
        QJniObject::fromString(task.link).object<jstring>(), QJniObject::fromString(task.mode).object<jstring>(),
        QJniObject::fromString(task.videoFormat).object<jstring>(), QJniObject::fromString(task.imageFormat).object<jstring>(), task.audioBitrate);
#else
    m_busy = false; m_activeKey.clear(); state.status = "请在安卓设备上运行。";
#endif
    emit changed();
}

void Controller::chooseLocalVideo() {
    if (busy()) return;
    setPage(1);
#ifdef Q_OS_ANDROID
    m_pickerPending = true;
    QJniObject::callStaticMethod<void>(bridge, "pickVideo", "(I)V", audioBitrate());
#else
    m_audio.hasTask = true; m_audio.title = "选择本地视频"; m_audio.status = "请在安卓设备上选择视频。";
#endif
    emit changed();
}
void Controller::extractLastAudio() {
    if (busy() || !canExtractLast()) return;
    setPage(1);
#ifdef Q_OS_ANDROID
    m_pickerPending = true;
    QJniObject::callStaticMethod<void>(bridge, "extractLastAudio", "(I)V", audioBitrate());
#else
    m_audio.hasTask = true; m_audio.title = "提取 MP3"; m_audio.status = "请在安卓设备上运行。";
#endif
    emit changed();
}
void Controller::cancel() {
    if (!taskBusy()) return;
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(bridge, "cancel", "()V");
#endif
    auto &state = current(); state.status = "正在取消…";
#ifndef Q_OS_ANDROID
    m_busy = false; state.progress = 0; state.status = "已取消，可重试。";
#endif
    emit changed();
}
void Controller::login() {
#ifdef Q_OS_ANDROID
    const auto platform = current().platform;
    QString key = platform == "Bilibili" ? "bilibili" : platform == "抖音" ? "douyin" :
                  platform == "Instagram" ? "instagram" : platform == "YouTube" ? "youtube" : "x";
    QJniObject::callStaticMethod<void>(bridge, "login", "(Ljava/lang/String;)V", QJniObject::fromString(key).object<jstring>());
#endif
}
void Controller::openResult() {
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(bridge, "openResultForMode", "(Ljava/lang/String;Z)V",
                                    QJniObject::fromString(currentMode()).object<jstring>(), false);
#endif
}
void Controller::shareResult() {
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(bridge, "openResultForMode", "(Ljava/lang/String;Z)V",
                                    QJniObject::fromString(currentMode()).object<jstring>(), true);
#endif
}
void Controller::consume(const QString &line) {
    const auto data = QJsonDocument::fromJson(line.toUtf8()).object();
    if (data.isEmpty()) return;
    const auto event = data["event"].toString();
    if(event=="library") {
        m_library=data["items"].toArray().toVariantList();m_saveLocation=data["save_location"].toString(m_saveLocation);m_storageBusy=data["storage_busy"].toBool();emit changed();return;
    }
    if(event=="storage") {m_libraryStatus=data["message"].toString();m_storageBusy=data["busy"].toBool();m_saveLocation=data["save_location"].toString(m_saveLocation);emit changed();return;}
    if(event=="library_error") {m_libraryStatus=data["message"].toString();emit changed();return;}
    if (event == "update") {
        if (data.contains("error")) {
            if (data["manual"].toBool()) m_updateStatus = data["error"].toString();
        } else {
            m_updateAvailable = data["available"].toBool(); m_updateUrl = data["url"].toString();
            m_updateStatus = m_updateAvailable ? "发现新版本 " + data["version"].toString()
                                              : data["manual"].toBool() ? "已经是最新版本" : "";
        }
        emit changed(); return;
    }
    const auto mode = data["mode"].toString(m_activeMode.isEmpty() ? currentMode() : m_activeMode);
    auto &state = forMode(mode);
    if (event == "local_cancelled") { m_pickerPending = false; emit changed(); return; }
    if (event == "cancelled") {
        if (mode == m_activeMode) m_busy = false;
        state.progress = 0; state.status = "已取消，可重试。";
        emit changed(); return;
    }
    if (event == "local_selected") {
        m_pickerPending = false; m_busy = true; m_activeMode = "audio";
        m_audio.hasTask = true; m_audio.result = {}; m_audio.logs.clear(); m_audio.progress = -1;
        m_audio.title = data["title"].toString(); m_audio.status = "正在读取本地视频…"; m_audio.details.clear();
    } else if (event == "stage" || event == "login_source") {
        state.hasTask = true; state.status = data["message"].toString();
    } else if (event == "metadata") {
        state.title = data["title"].toString();
        state.details = data["content_type"] == "gallery" ? QString("%1 张图片 · %2 段实况").arg(data["image_count"].toInt()).arg(data["live_photo_count"].toInt())
                                                        : "原片时长 " + clockText(data["duration"].toDouble());
    } else if (event == "progress") {
        const double total = data["total"].toDouble();
        state.progress = total > 0 ? qMin(1.0, data["downloaded"].toDouble() / total) : -1;
        state.status = mode == "audio" ? "正在下载音轨…" : "正在下载画面与声音…";
        state.details = QString("%1 MB · %2 MB/s").arg(data["downloaded"].toDouble() / 1048576, 0, 'f', 1).arg(data["speed"].toDouble() / 1048576, 0, 'f', 1);
    } else if (event == "error") {
        state.hasTask = true; state.status = data["message"].toString(); state.progress = 0;
        if (mode == m_activeMode || m_pickerPending) { m_busy = false; m_pickerPending = false; }
        state.details = "可重试，或网页登录后再试。"; state.logs += state.status + '\n';
    } else if (event == "complete") {
        state.hasTask = true; state.result = data; state.progress = 1; state.title = data["title"].toString();
        if (mode == m_activeMode) m_busy = false;
        if (data["content_type"] == "gallery") {
            state.status = "导出完成";
            state.details = QString("%1 张图片 · %2 段实况 · %3 首配乐").arg(data["image_count"].toInt()).arg(data["live_photo_count"].toInt()).arg(data["music_count"].toInt());
        } else {
            state.status = mode == "audio" ? "MP3 已保存" : "视频已保存";
            state.details = QString("%1 · %2 MB").arg(clockText(data["duration"].toDouble())).arg(data["size"].toDouble() / 1048576, 0, 'f', 1);
        }
    } else if (event == "log") {
        state.logs += data["message"].toString() + '\n';
        if (state.logs.size() > 16000) state.logs = state.logs.right(12000);
    }
    emit changed();
}


static constexpr auto mediaLibrary = "com/localvideodownloader/app/MediaLibrary";
void Controller::refreshLibrary() {
    m_libraryStatus.clear();
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(mediaLibrary,"requestSnapshot","()V");
#endif
}
void Controller::openLibraryItem(const QString &id) {
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(mediaLibrary,"open","(Ljava/lang/String;)V",QJniObject::fromString(id).object<jstring>());
#endif
}
void Controller::shareLibraryItem(const QString &id) {
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(mediaLibrary,"share","(Ljava/lang/String;)V",QJniObject::fromString(id).object<jstring>());
#endif
}
void Controller::removeLibraryItem(const QString &id) {
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(mediaLibrary,"remove","(Ljava/lang/String;)V",QJniObject::fromString(id).object<jstring>());
#endif
}
void Controller::extractLibraryAudio(const QString &id) {
    if(busy())return;setPage(1);
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(mediaLibrary,"extractAudio","(Ljava/lang/String;I)V",QJniObject::fromString(id).object<jstring>(),audioBitrate());
#endif
}
void Controller::chooseSaveLocation() {
    if(busy())return;
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(mediaLibrary,"chooseDirectory","()V");
#endif
}
void Controller::resetSaveLocation() {
    if(busy())return;
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(mediaLibrary,"resetDirectory","()V");
#endif
}
