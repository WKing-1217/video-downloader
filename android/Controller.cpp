#include "Controller.h"
#include <QClipboard>
#include <QGuiApplication>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QTimer>
#include <QUrl>
#include <QDesktopServices>
#include <QSettings>
#ifdef Q_OS_ANDROID
#include <QJniObject>
#include <QJniEnvironment>
#include <QCoreApplication>
#endif

static Controller *controller = nullptr;
static constexpr auto bridge = "com/localvideodownloader/app/DownloadBridge";
static QString clockText(double seconds) {
    int s = qRound(seconds);
    return QString("%1:%2").arg(s / 60, 2, 10, QChar('0')).arg(s % 60, 2, 10, QChar('0'));
}
Controller::Controller(QObject *parent) : QObject(parent) {
    controller = this;
#ifdef Q_OS_ANDROID
    auto timer = new QTimer(this);
    connect(timer, &QTimer::timeout, this, [this] {
        const auto text = QJniObject::callStaticObjectMethod(bridge, "takeSharedText", "()Ljava/lang/String;").toString();
        if (!text.isEmpty() && !m_busy) setLink(text);
        const auto event = QJniObject::callStaticObjectMethod(bridge, "takeEvents", "()Ljava/lang/String;").toString();
        for (const auto &line : event.split('\n', Qt::SkipEmptyParts)) consume(line);
    });
    timer->start(150);
    if (autoUpdate()) QTimer::singleShot(2500, this, [this] { checkForUpdates(false); });
#endif
}
QString Controller::version() const { return QStringLiteral(APP_VERSION); }
bool Controller::autoUpdate() const { return QSettings("LocalVideoDownloader", "VideoDownloader").value("autoUpdate", true).toBool(); }
void Controller::setAutoUpdate(bool enabled) {
    QSettings("LocalVideoDownloader", "VideoDownloader").setValue("autoUpdate", enabled);
    emit changed();
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
    m_link = text;
    m_platform.clear();
    QRegularExpression urls("https?://[^\\s<>\"“”。；！？]+", QRegularExpression::CaseInsensitiveOption);
    auto matches = urls.globalMatch(text);
    while (matches.hasNext()) {
        QUrl u(matches.next().captured());
        if (!u.userInfo().isEmpty() || u.port() != -1) continue;
        const auto h = u.host().toLower();
        if (QStringList{"bilibili.com","www.bilibili.com","m.bilibili.com","b23.tv"}.contains(h)) m_platform = "Bilibili";
        if (QStringList{"douyin.com","www.douyin.com","v.douyin.com","m.douyin.com","iesdouyin.com","www.iesdouyin.com"}.contains(h)) m_platform = "抖音";
        if (QStringList{"x.com","www.x.com","mobile.x.com","twitter.com","www.twitter.com","mobile.twitter.com","m.twitter.com","t.co"}.contains(h)) m_platform = "X / Twitter";
        if (!m_platform.isEmpty()) break;
    }
    emit changed();
}
void Controller::paste() { setLink(QGuiApplication::clipboard()->text()); }
void Controller::start() {
    if (m_busy) return;
    if (m_platform.isEmpty()) { m_status = "请粘贴 Bilibili、抖音或 X 的作品链接。"; emit changed(); return; }
    m_busy = true; m_progress = -1; m_result = {}; m_logs.clear();
    m_title = "正在读取作品信息"; m_status = "正在连接 " + m_platform + "…";
    m_details = "正在读取原始画质与音质…";
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(bridge,"start","(Ljava/lang/String;)V",QJniObject::fromString(m_link).object<jstring>());
#else
    m_busy = false; m_status = "请在安卓设备上运行下载。";
#endif
    emit changed();
}
void Controller::cancel() {
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(bridge,"cancel","()V");
#endif
    m_busy = false; m_progress = 0; m_status = "已取消，可重新下载。"; emit changed();
}
void Controller::login() {
#ifdef Q_OS_ANDROID
    QString key = m_platform == "Bilibili" ? "bilibili" : m_platform == "抖音" ? "douyin" : "x";
    QJniObject::callStaticMethod<void>(bridge,"login","(Ljava/lang/String;)V",QJniObject::fromString(key).object<jstring>());
#endif
}
void Controller::openResult() {
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(bridge,"openResult","(Z)V",false);
#endif
}
void Controller::shareResult() {
#ifdef Q_OS_ANDROID
    QJniObject::callStaticMethod<void>(bridge,"openResult","(Z)V",true);
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
            m_updateAvailable = data["available"].toBool();
            m_updateUrl = data["url"].toString();
            m_updateStatus = m_updateAvailable ? "发现新版本 " + data["version"].toString()
                                              : data["manual"].toBool() ? "已经是最新版本" : "";
        }
        emit changed();
        return;
    }
    if (event == "stage" || event == "login_source") m_status = data["message"].toString();
    else if (event == "metadata") {
        m_title = data["title"].toString();
        m_details = data["content_type"] == "gallery" ? QString("%1 张图片 · %2 段实况").arg(data["image_count"].toInt()).arg(data["live_photo_count"].toInt())
                                                     : "原片时长 " + clockText(data["duration"].toDouble());
    } else if (event == "progress") {
        const double total = data["total"].toDouble();
        m_progress = total > 0 ? qMin(1.0, data["downloaded"].toDouble() / total) : -1;
        m_status = "正在下载画面与声音…";
        m_details = QString("%1 MB · %2 MB/s").arg(data["downloaded"].toDouble()/1048576,0,'f',1).arg(data["speed"].toDouble()/1048576,0,'f',1);
    } else if (event == "error") {
        m_status = "下载失败：" + data["message"].toString(); m_busy = false; m_progress = 0;
        m_details = "链接已保留，可重新下载或网页登录后重试。";
        m_logs += m_status + '\n';
    } else if (event == "complete") {
        m_result = data; m_busy = false; m_progress = 1; m_title = data["title"].toString();
        if (data["content_type"] == "gallery") {
            m_status = "导出完成 · 原图、实况和配乐已检查";
            m_details = QString("%1 张图片 · %2 段实况 · %3 首配乐").arg(data["image_count"].toInt()).arg(data["live_photo_count"].toInt()).arg(data["music_count"].toInt());
        } else {
            m_status = "下载完成 · 视频、音频和完整时长已检查";
            m_details = QString("%1 × %2 · %3 · %4 MB").arg(data["width"].toInt()).arg(data["height"].toInt()).arg(clockText(data["duration"].toDouble())).arg(data["size"].toDouble()/1048576,0,'f',1);
        }
    } else if (event == "log") {
        m_logs += data["message"].toString() + '\n';
        if (m_logs.size() > 16000) m_logs = m_logs.right(12000);
    }
    emit changed();
}
