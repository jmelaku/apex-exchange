#pragma once

#include "apex/matching_engine.hpp"
#include <string>

namespace apex {
std::string handle_command(MatchingEngine& engine, const std::string& line);
}
