/*  Claude GG Pokemon GO Lock (the lock screen of the phone and the dimmed game)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PokemonGoLock.h.  What the Python code does is followed line by line, down to the order of the questions that it asks.
 *
 */

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <vector>
#include <opencv2/core.hpp>
#include "ClaudeGG_PokemonGoLock.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Lock{

namespace{

//  The little lock of the game is dragged one of these ways (UNLOCK_SWIPES).
struct Drag{
    int x1, y1, x2, y2;
};
const std::array<Drag, 3> UNLOCK_SWIPES{{
    {896, 1208, 896, 450},                              //  the lock up
    {896, 1208, 1600, 1208},                            //  to the right
    {896, 1208, 896, 1950},                             //  down
}};

}


bool is_dimmed(const cv::Mat& img){
    //  v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 2]; np.percentile(v, 99.5) < DARK_LIMIT
    //  (the V of HSV is the biggest of the three numbers of a pixel; the percentile is read from the count of every value)
    if (img.empty()){
        return false;
    }
    std::array<std::int64_t, 256> count{};
    std::int64_t total = 0;
    if (img.type() == CV_8UC3){
        for (int y = 0; y < img.rows; y++){
            const cv::Vec3b* row = img.ptr<cv::Vec3b>(y);
            for (int x = 0; x < img.cols; x++){
                count[std::max({row[x][0], row[x][1], row[x][2]})]++;
            }
        }
        total = (std::int64_t)img.rows * img.cols;
    }else{
        return false;
    }
    //  numpy: the position is (n - 1) * 0.995 in the sorted numbers; between the two pixels around it the value is a straight line.
    const double position = (double)(total - 1) * (99.5 / 100.0);
    const std::int64_t below = (std::int64_t)std::floor(position);
    const double gamma = position - (double)below;
    const auto value_at = [&](std::int64_t rank) -> double{
        rank = std::min(rank, total - 1);
        std::int64_t seen = 0;
        for (int v = 0; v < 256; v++){
            seen += count[(size_t)v];
            if (rank < seen){
                return v;
            }
        }
        return 255;
    };
    const double a = value_at(below);
    const double b = value_at(below + 1);
    const double diff = b - a;
    const double percentile = gamma >= 0.5 ? b - diff * (1 - gamma) : a + diff * gamma;
    return percentile < DARK_LIMIT;
}


bool unlock(Host& host){
    if (!host.keyguard_showing()){
        return false;
    }
    host.log("lock screen active - unlocking");
    host.dismiss_keyguard();
    host.sleep(1.5);
    if (host.keyguard_showing()){
        host.swipe(884, 1900, 884, 500, 300);           //  swipe up, like by hand
        host.sleep(1.5);
    }
    if (host.keyguard_showing()){
        host.log("unlock failed - is there a PIN/pattern?");
        return false;
    }
    return true;
}


cv::Mat unlock_game(Host& host, const cv::Mat& first){
    cv::Mat img = first;
    if (!is_dimmed(img)){
        return img;
    }
    for (const Drag& drag : UNLOCK_SWIPES){
        host.log(QString("game is dimmed/locked - tap + drag lock (%1,%2) -> (%3,%4)").arg(drag.x1).arg(drag.y1).arg(drag.x2).arg(drag.y2));
        host.tap(884, 700);                             //  the first tap makes the little lock appear
        host.sleep(1.2);
        host.swipe(drag.x1, drag.y1, drag.x2, drag.y2, 700);
        host.sleep(2.5);
        img = host.screenshot();
        if (!is_dimmed(img)){
            host.log("game unlocked");
            return img;
        }
    }
    host.log("game stays dimmed");
    return img;
}

cv::Mat unlock_game(Host& host){
    return unlock_game(host, host.screenshot());
}


}
}
}
}
