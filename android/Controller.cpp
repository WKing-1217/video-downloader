#include "Controller.h"
#include <QClipboard>
#include <QGuiApplication>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QTimer>
#include <QUrl>
#include <QDesktopServices>
#include <QSettings>
#include <QList>
#include <QStringList>
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
        if (!text.isEmpty() && !busy()) { setPage(0); setLink(text); }
        const auto events = QJniObject::callStaticObjectMethod(bridge, "takeEvents", "()Ljava/lang/String;").toString();
        for (const auto &line : events.split('\n', Qt::SkipEmptyParts)) consume(line);
    });
    timer->start(150);
    if (autoUpdate()) QTimer::singleShot(2500, this, [this] { checkForUpdates(false); });
#endif
}
void Controller::setPage(int value) {
    if (value < 0 || value > 2 || m_page == value) return;
    m_page = value; emit changed();
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
void Controller::setLink(const QString &text) {
    auto &state = current();
    state.link = text; state.platform.clear();
    QRegularExpression urls("https?://[^\\s<>\"“”。；！？]+", QRegularExpression::CaseInsensitiveOption);
    auto matches = urls.globalMatch(text);
    while (matches.hasNext()) {
        QUrl u(matches.next().captured());
        if (!u.userInfo().isEmpty() || u.port() != -1) continue;
        const auto h = u.host().toLower();
        if (QStringList{"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"}.contains(h)) state.platform = "Bilibili";
        if (QStringList{"douyin.com", "www.douyin.com", "v.douyin.com", "m.douyin.com", "iesdouyin.com", "www.iesdouyin.com"}.contains(h)) state.platform = "抖音";
        if (QStringList{"x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com", "m.twitter.com", "t.co"}.contains(h)) state.platform = "X";
        if (!state.platform.isEmpty()) break;
    }
    emit changed();
}
void Controller::paste() { setLink(QGuiApplication::clipboard()->text()); }
void Controller::start() {
    if (busy()) return;
    auto &state = current();
    const auto mode = currentMode();
    if (state.platform.isEmpty()) {
        state.hasTask = true; state.title = "未能开始";
        state.result = {}; state.progress = 0; state.details.clear();
        state.status = "请粘贴 Bilibili、抖音或 X 的作品链接。";
        emit changed(); return;
    }
    m_busy = true; m_activeMode = mode;
    state.progress = -1; state.result = {}; state.logs.clear(); state.hasTask = true;
    state.title = "正在读取作品信息"; state.status = "正在连接 " + state.platform + "…";
    state.details.clear();
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(bridge, "start", "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;I)V",
        QJniObject::fromString(state.link).object<jstring>(), QJniObject::fromString(mode).object<jstring>(),
        QJniObject::fromString(videoFormat()).object<jstring>(), QJniObject::fromString(imageFormat()).object<jstring>(), audioBitrate());
#else
    m_busy = false; state.status = "请在安卓设备上运行。";
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
    QString key = platform == "Bilibili" ? "bilibili" : platform == "抖音" ? "douyin" : "x";
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

